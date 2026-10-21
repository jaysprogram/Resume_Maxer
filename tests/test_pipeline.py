"""The retry loop, with a scripted writer and compiler: no Claude, no TeX."""

import copy

import pytest
from anthropic.types import Usage

from resume_maxer import pipeline
from resume_maxer.claude import Answer, ClaudeError
from resume_maxer.compile import CompileResult, LineWidth
from resume_maxer.judge import Verdict
from resume_maxer.pipeline import MAX_ATTEMPTS, TailorError, tailor
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.schema import Master
from resume_maxer.writer import WriterResult

JD = "We want Go and PostgreSQL."


@pytest.fixture
def master(sample_data) -> Master:
    return Master.model_validate(sample_data)


def written(doc_data=None, cost=0.10, detail=None) -> WriterResult:
    return WriterResult(
        parsed=ResumeDoc.model_validate(doc_data) if doc_data is not None else None,
        stop_reason="completed" if doc_data is not None else "refusal",
        usage=Usage(input_tokens=0, output_tokens=0),
        cost_usd=cost,
        request_id=None,
        detail=detail,
    )


class Script:
    """Hands out writer results and compile results in order, recording each call."""

    def __init__(self, results, pages=None, widths=None, empty=None):
        self.results = list(results)
        self.pages = list(pages or [1] * len(self.results))
        self.widths = list(widths or [[] for _ in self.results])
        # Empty bullet lines at the bottom of each compiled page; None: not measured.
        self.empty = list(empty or [None] * len(self.results))
        self.repairs = []
        self.compiles = 0

    def write(self, master_json, job_description, *, repair=None):
        assert job_description == JD
        self.repairs.append(repair)
        return self.results.pop(0)

    def compile(self, tex):
        self.compiles += 1
        return CompileResult(
            pdf=b"%PDF-" + str(self.compiles).encode(),
            pages=self.pages.pop(0),
            widths=self.widths.pop(0),
            missing_glyphs=[],
            log="",
            **self._fill(self.empty.pop(0)),
        )

    @staticmethod
    def _fill(empty_lines):
        if empty_lines is None:
            return {}
        return {"used_pt": 731.4 - empty_lines * 12.6, "page_pt": 731.4}


def run(master, script):
    return tailor(master, "{}", JD, write=script.write, compile_fn=script.compile)


def test_passing_draft_is_used_without_a_repair(master, sample_doc_data):
    script = Script([written(sample_doc_data)])
    result = run(master, script)
    assert result.passed and result.failures == []
    assert script.repairs == [None]  # one call, no repair
    assert result.pdf == b"%PDF-1"


def test_failed_draft_is_repaired_with_its_failures(master, sample_doc_data):
    script = Script(
        [written(sample_doc_data, cost=0.17), written(sample_doc_data, cost=0.06)],
        widths=[[LineWidth("ACME.1", 104.0, 100.0)], [LineWidth("ACME.1", 95.0, 100.0)]],
    )
    result = run(master, script)

    first, repair = script.repairs
    assert first is None
    assert repair.previous == ResumeDoc.model_validate(sample_doc_data)
    [failure] = repair.failures
    assert failure.startswith("ACME.1 uses 104% of the line")
    assert result.passed and result.pdf == b"%PDF-2"
    assert result.cost_usd == pytest.approx(0.23)


def test_never_more_than_one_repair_and_the_best_attempt_wins(master, sample_doc_data):
    worse = written(sample_doc_data)
    better = written(sample_doc_data)
    script = Script(
        [worse, better],
        pages=[2, 1],  # the draft also runs onto a second page
        widths=[[LineWidth("ACME.1", 104.0, 100.0)], [LineWidth("NWL.1", 101.0, 100.0)]],
    )
    result = run(master, script)

    assert len(script.repairs) == MAX_ATTEMPTS == 2
    assert not result.passed
    [failure] = result.failures  # the repair's single failure, not the draft's two
    assert failure.startswith("NWL.1 uses 101%")
    assert result.pdf == b"%PDF-2"


def test_tie_goes_to_the_repaired_attempt(master, sample_doc_data):
    script = Script(
        [written(sample_doc_data), written(sample_doc_data)],
        widths=[[LineWidth("ACME.1", 104.0, 100.0)], [LineWidth("NWL.1", 104.0, 100.0)]],
    )
    result = run(master, script)
    assert result.failures[0].startswith("NWL.1")


def test_no_document_means_the_retry_starts_fresh(master, sample_doc_data):
    script = Script([written(None, detail="refused"), written(sample_doc_data)], pages=[1])
    result = run(master, script)
    assert script.repairs == [None, None]  # nothing to repair, so a fresh draft
    assert result.passed


def test_unrenderable_document_is_repaired_without_compiling(master, sample_doc_data):
    broken = copy.deepcopy(sample_doc_data)
    broken["experience"][0]["entry_id"] = "NOPE"
    script = Script([written(broken), written(sample_doc_data)], pages=[1])
    result = run(master, script)

    assert script.compiles == 1  # only the repaired document was compiled
    assert script.repairs[1].failures == ["unknown entry 'NOPE'"]
    assert result.passed


def test_no_document_from_any_attempt_raises_with_the_reasons(master):
    script = Script([written(None, detail="refused"), written(None, detail="timed out")])
    with pytest.raises(TailorError, match="refused; timed out"):
        run(master, script)


def test_under_filled_draft_gets_one_repair_asking_for_content(master, sample_doc_data):
    script = Script([written(sample_doc_data), written(sample_doc_data)], empty=[5.0, 1.5])
    result = run(master, script)

    [shortfall] = script.repairs[1].failures
    assert shortfall.startswith("the page has about 5 empty lines")
    assert result.passed and result.shortfalls == [] and result.pdf == b"%PDF-2"


def test_under_filled_draft_beats_a_repair_that_overflowed(master, sample_doc_data):
    # The repair added too much and spilled onto a second page: keep the draft.
    script = Script(
        [written(sample_doc_data), written(sample_doc_data)], pages=[1, 2], empty=[5.0, None]
    )
    result = run(master, script)

    assert result.passed  # a shortfall is not a failure
    assert result.pdf == b"%PDF-1"
    assert result.shortfalls[0].startswith("the page has about 5 empty lines")


def test_well_filled_passing_draft_needs_no_repair(master, sample_doc_data):
    script = Script([written(sample_doc_data)], empty=[1.6])
    assert run(master, script).passed and script.repairs == [None]


# --- the judge: advice on the final page, never a repair ----------------------


class FakeJudge:
    def __init__(self, verdict=None, error=None, cost=0.001):
        self.verdict, self.error, self.cost, self.calls = verdict, error, cost, []

    def __call__(self, resume_text, job_description):
        self.calls.append((resume_text, job_description))
        if self.error:
            raise self.error
        return Answer(
            parsed=self.verdict,
            stop_reason="completed",
            usage=Usage(input_tokens=0, output_tokens=0),
            cost_usd=self.cost,
            request_id=None,
            detail=None if self.verdict else "refused",
        )


@pytest.fixture
def page_text(monkeypatch):
    # The scripted compiler's PDFs are fake bytes; give the judge readable text.
    monkeypatch.setattr(pipeline, "pdf_text", lambda pdf: f"text of {pdf.decode()} , here")


def test_judge_scores_the_best_page_once_and_never_triggers_a_repair(
    master, sample_doc_data, page_text
):
    verdict = Verdict(score=40, summary="Weak fit.", gaps=["No Go"])  # far below any bar
    judge = FakeJudge(verdict)
    script = Script([written(sample_doc_data, cost=0.15)])
    result = tailor(master, "{}", JD, write=script.write, compile_fn=script.compile, judge=judge)

    assert script.repairs == [None]  # a low score asked for nothing
    assert result.passed and result.verdict == verdict
    # Cleaned text: the extractor's stray space before a comma is gone.
    assert judge.calls == [("text of %PDF-1, here", JD)]
    assert result.cost_usd == pytest.approx(0.151)


def test_judge_failure_keeps_the_resume(master, sample_doc_data, page_text):
    judge = FakeJudge(error=ClaudeError("Claude Code did not answer within 1200s."))
    script = Script([written(sample_doc_data)])
    result = tailor(master, "{}", JD, write=script.write, compile_fn=script.compile, judge=judge)
    assert result.passed and result.pdf == b"%PDF-1"
    assert result.verdict is None
    assert result.judge_note == "judge unavailable: Claude Code did not answer within 1200s."


def test_judge_without_a_verdict_leaves_a_note(master, sample_doc_data, page_text):
    script = Script([written(sample_doc_data)])
    result = tailor(
        master, "{}", JD, write=script.write, compile_fn=script.compile, judge=FakeJudge()
    )
    assert result.judge_note == "judge gave no verdict: refused"


def test_no_judge_when_there_is_no_page(master, sample_doc_data):
    broken = copy.deepcopy(sample_doc_data)
    broken["experience"][0]["entry_id"] = "NOPE"
    judge = FakeJudge(Verdict(score=90, summary="x", gaps=[]))
    script = Script([written(broken), written(broken)])
    result = tailor(master, "{}", JD, write=script.write, compile_fn=script.compile, judge=judge)
    assert result.pdf is None and judge.calls == [] and result.verdict is None
