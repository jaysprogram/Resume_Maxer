"""Background runs: one folder per run, statuses that survive restarts."""

import json

import pytest
from anthropic.types import Usage

from resume_maxer.claude import Answer
from resume_maxer.jobs import MAX_POSTING_CHARS, PostingError, RunStore, clean_label
from resume_maxer.judge import Verdict
from resume_maxer.pipeline import Attempt, Tailored
from resume_maxer.resume_doc import ResumeDoc


def tailored(sample_doc_data, **extra) -> Tailored:
    writer = Answer(
        parsed=None, stop_reason="completed", usage=Usage(input_tokens=0, output_tokens=0),
        cost_usd=0.07, request_id=None,
    )  # fmt: skip
    return Tailored(
        doc=ResumeDoc.model_validate(sample_doc_data),
        pdf=b"%PDF-run",
        failures=[],
        flags=["ACME.1 '...': uses 'agile' from the posting"],
        attempts=[Attempt(writer, None, None)],
        **extra,
    )


def test_run_goes_from_queued_to_done_with_its_files(tmp_path, sample_doc_data):
    verdict = Verdict(score=81, summary="Solid.", gaps=[f"gap {i}" for i in range(7)])
    seen = []
    store = RunStore(
        tmp_path,
        lambda posting: seen.append(posting) or tailored(sample_doc_data, verdict=verdict),
    )
    run = store.create("  We want Go.  ", "Acme / Backend!")
    assert run.state == "queued" and run.label == "Acme Backend"
    store.wait_idle()

    done = store.get(run.id)
    assert seen == ["We want Go."]  # trimmed
    assert (done.state, done.passed, done.has_pdf, done.cost_usd) == ("done", True, True, 0.07)
    assert done.verdict.score == 81 and len(done.verdict.gaps) == 5
    assert done.flags == ["ACME.1 '...': uses 'agile' from the posting"]
    assert store.pdf_path(run.id).read_bytes() == b"%PDF-run"
    assert json.loads((tmp_path / run.id / "resume.json").read_text("utf-8"))["skills"]


def test_failed_run_records_its_message(tmp_path):
    def boom(posting):
        raise RuntimeError("Tectonic not found. Install it, or set TECTONIC.")

    store = RunStore(tmp_path, boom)
    run = store.create("We want Go.")
    store.wait_idle()
    failed = store.get(run.id)
    assert failed.state == "error"
    assert failed.error == "Tectonic not found. Install it, or set TECTONIC."
    assert "Traceback" in (tmp_path / run.id / "error.txt").read_text("utf-8")
    assert store.pdf_path(run.id) is None


def test_run_cut_off_by_a_restart_is_marked_interrupted(tmp_path, sample_doc_data):
    store = RunStore(tmp_path, lambda posting: tailored(sample_doc_data))
    run = store.create("We want Go.")
    store.wait_idle()
    # Simulate a crash mid-run: the status still says "running" on disk.
    status = store.get(run.id).model_copy(update={"state": "running"})
    (tmp_path / run.id / "status.json").write_text(status.model_dump_json(), "utf-8")

    restarted = RunStore(tmp_path, lambda posting: tailored(sample_doc_data))
    assert restarted.get(run.id).state == "interrupted"


@pytest.mark.parametrize(
    ("posting", "message"),
    [("   ", "empty"), ("x" * (MAX_POSTING_CHARS + 1), "limit is 50,000")],
    # Short ids: pytest puts the test id in an environment variable, and Windows
    # caps those at 32,767 characters, far below a 50,001-character posting.
    ids=["empty", "too-long"],
)
def test_bad_postings_are_refused_before_queueing(tmp_path, posting, message):
    store = RunStore(tmp_path, lambda posting: pytest.fail("must not run"))
    with pytest.raises(PostingError, match=message):
        store.create(posting)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id", ["../../etc", "..", "ABC", "a" * 31, "g" * 32, "a" * 33])
def test_only_exact_run_ids_reach_the_disk(tmp_path, run_id):
    store = RunStore(tmp_path, lambda posting: None)
    assert store.get(run_id) is None and store.pdf_path(run_id) is None


def test_runs_are_listed_newest_first(tmp_path, sample_doc_data):
    store = RunStore(tmp_path, lambda posting: tailored(sample_doc_data))
    ids = [store.create(f"posting {i}").id for i in range(3)]
    store.wait_idle()
    for i, run_id in enumerate(ids):  # created within one second: make the order explicit
        status = store.get(run_id).model_copy(update={"created": f"2026-10-20T10:00:0{i}+00:00"})
        (tmp_path / run_id / "status.json").write_text(status.model_dump_json(), "utf-8")
    assert [r.id for r in store.list()] == ids[::-1]


@pytest.mark.parametrize(
    ("label", "expected"),
    [("Acme: SWE Intern (2026)", "Acme SWE Intern 2026"), ("", "resume"), ("../..", "resume")],
)
def test_labels_are_safe_for_file_names(label, expected):
    assert clean_label(label) == expected
