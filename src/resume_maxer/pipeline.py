"""Tailor a resume to a job description: write, check, and repair once if anything failed.

Agreed flow: the writer drafts a document; code checks structure, numbers, page
count, line widths and glyphs. Any failure gets exactly one repair attempt that
sees the failed document and the precise failures. If that also fails, the best
attempt is returned with the list of what still fails, never silently.

The judge's score is advice only (calibration showed it barely separates a
tailored resume from an untailored one, and moves up to 11 points between runs
on the same page), so it is reported beside the result and never triggers a
repair.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from resume_maxer.checks import pdf_text
from resume_maxer.claude import Answer, ClaudeError
from resume_maxer.compile import CompileResult, compile_tex
from resume_maxer.judge import Verdict
from resume_maxer.render import render
from resume_maxer.resume_doc import ResumeDoc, problems
from resume_maxer.review import Review, review
from resume_maxer.schema import Master
from resume_maxer.writer import BACKEND, BACKENDS, Repair, WriterResult

# One draft plus one repair, as agreed: a second repair costs another call for
# diminishing returns, and a person reviews whatever still fails.
MAX_ATTEMPTS = 2


class TailorError(RuntimeError):
    """No attempt produced a resume document at all."""


@dataclass(frozen=True)
class Attempt:
    writer: WriterResult
    review: Review | None  # None when the writer gave no document
    compiled: CompileResult | None  # None when the document could not be rendered


@dataclass(frozen=True)
class Tailored:
    doc: ResumeDoc
    pdf: bytes | None  # None only when even the best attempt could not be rendered
    failures: list[str]  # what still fails; empty means every check passed
    flags: list[str]  # for review, never retried
    attempts: list[Attempt]
    shortfalls: list[str] = field(default_factory=list)  # room to improve; not failures
    verdict: Verdict | None = None  # the judge's advice, when it ran and answered
    judge_note: str | None = None  # why there is no verdict, when the judge was asked
    judge_cost_usd: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def cost_usd(self) -> float:
        return sum(a.writer.cost_usd for a in self.attempts) + self.judge_cost_usd


def check(
    doc: ResumeDoc,
    master: Master,
    compile_fn: Callable[[str], CompileResult] = compile_tex,
    job_description: str | None = None,
) -> tuple[Review, CompileResult | None]:
    """Review a document, compiling it when it can be rendered at all."""
    if problems(doc, master):  # render refuses these; review reports them
        return review(doc, master, None, job_description), None
    compiled = compile_fn(render(doc, master))
    return review(doc, master, compiled, job_description), compiled


def _check(result: WriterResult, master: Master, compile_fn, job_description: str) -> Attempt:
    if result.parsed is None:
        return Attempt(result, None, None)
    return Attempt(result, *check(result.parsed, master, compile_fn, job_description))


def _rank(attempt: Attempt) -> tuple:
    # A document beats none; a rendered one beats an unrendered one; then fewer
    # failures; only then fewer shortfalls, so an under-filled one-page draft
    # beats a repair that overflowed onto two pages.
    if attempt.review is None:
        return (0, 0, 0, 0)
    r = attempt.review
    return (1, attempt.compiled is not None, -len(r.failures), -len(r.shortfalls))


def judge_text(pdf: bytes) -> str:
    """The resume as an ATS extracts it, minus the extractor's stray space before
    punctuation ("Angular ,"), which is not on the page and misled the judge once."""
    return re.sub(r"[ \t]+([,.;:)])", r"\1", pdf_text(pdf))


def _judge(judge, pdf: bytes, job_description: str) -> dict:
    """Ask the judge; any trouble becomes a note, never a lost resume."""
    try:
        answer: Answer[Verdict] = judge(judge_text(pdf), job_description)
    except ClaudeError as exc:
        return {"judge_note": f"judge unavailable: {exc}"}
    note = None if answer.parsed else f"judge gave no verdict: {answer.detail}"
    return {"verdict": answer.parsed, "judge_note": note, "judge_cost_usd": answer.cost_usd}


def tailor(
    master: Master,
    master_json: str,
    job_description: str,
    *,
    write: Callable[..., WriterResult] | None = None,
    compile_fn: Callable[[str], CompileResult] = compile_tex,
    judge: Callable[[str, str], Answer[Verdict]] | None = None,
) -> Tailored:
    """Write, check and repair once; then, if `judge` is given, score the result."""
    write = write or BACKENDS[BACKEND]
    attempts: list[Attempt] = []
    repair = None
    for _ in range(MAX_ATTEMPTS):
        drafted = write(master_json, job_description, repair=repair)
        attempt = _check(drafted, master, compile_fn, job_description)
        attempts.append(attempt)
        if attempt.review is not None and attempt.review.passed and not attempt.review.shortfalls:
            break
        # A document is repaired; no document means the next try starts fresh.
        if attempt.review is not None:
            repair = Repair(
                attempt.writer.parsed, attempt.review.failures + attempt.review.shortfalls
            )

    # max() keeps the first of equals, so reverse: on a tie the later (repaired) attempt wins.
    best = max(reversed(attempts), key=_rank)
    if best.review is None:
        reasons = "; ".join(a.writer.detail or "no document" for a in attempts)
        raise TailorError(f"the writer produced no resume document ({reasons})")
    pdf = best.compiled.pdf if best.compiled else None
    judged = _judge(judge, pdf, job_description) if judge and pdf else {}
    return Tailored(
        doc=best.writer.parsed,
        pdf=pdf,
        failures=best.review.failures,
        flags=best.review.flags,
        attempts=attempts,
        shortfalls=best.review.shortfalls,
        **judged,
    )
