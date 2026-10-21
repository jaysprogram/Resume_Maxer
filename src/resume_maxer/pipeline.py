"""Tailor a resume to a job description: write, check, and repair once if anything failed.

Agreed flow: the writer drafts a document; code checks structure, numbers, page
count, line widths and glyphs. Any failure gets exactly one repair attempt that
sees the failed document and the precise failures. If that also fails, the best
attempt is returned with the list of what still fails, never silently.
"""

from collections.abc import Callable
from dataclasses import dataclass

from resume_maxer.compile import CompileResult, compile_tex
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

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def cost_usd(self) -> float:
        return sum(a.writer.cost_usd for a in self.attempts)


def check(
    doc: ResumeDoc, master: Master, compile_fn: Callable[[str], CompileResult] = compile_tex
) -> tuple[Review, CompileResult | None]:
    """Review a document, compiling it when it can be rendered at all."""
    if problems(doc, master):  # render refuses these; review reports them
        return review(doc, master, None), None
    compiled = compile_fn(render(doc, master))
    return review(doc, master, compiled), compiled


def _check(result: WriterResult, master: Master, compile_fn) -> Attempt:
    if result.doc is None:
        return Attempt(result, None, None)
    return Attempt(result, *check(result.doc, master, compile_fn))


def _rank(attempt: Attempt) -> tuple:
    # A document beats none; a rendered one beats an unrendered one; then fewer failures.
    if attempt.review is None:
        return (0, 0, 0)
    return (1, attempt.compiled is not None, -len(attempt.review.failures))


def tailor(
    master: Master,
    master_json: str,
    job_description: str,
    *,
    write: Callable[..., WriterResult] | None = None,
    compile_fn: Callable[[str], CompileResult] = compile_tex,
) -> Tailored:
    write = write or BACKENDS[BACKEND]
    attempts: list[Attempt] = []
    repair = None
    for _ in range(MAX_ATTEMPTS):
        attempt = _check(write(master_json, job_description, repair=repair), master, compile_fn)
        attempts.append(attempt)
        if attempt.review is not None and attempt.review.passed:
            break
        # A document is repaired; no document means the next try starts fresh.
        if attempt.review is not None:
            repair = Repair(attempt.writer.doc, attempt.review.failures)

    # max() keeps the first of equals, so reverse: on a tie the later (repaired) attempt wins.
    best = max(reversed(attempts), key=_rank)
    if best.review is None:
        reasons = "; ".join(a.writer.detail or "no document" for a in attempts)
        raise TailorError(f"the writer produced no resume document ({reasons})")
    return Tailored(
        doc=best.writer.doc,
        pdf=best.compiled.pdf if best.compiled else None,
        failures=best.review.failures,
        flags=best.review.flags,
        attempts=attempts,
    )
