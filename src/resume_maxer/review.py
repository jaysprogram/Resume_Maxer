"""Turn what the checks measured into failures the writer can fix, and flags for a person.

Policy only. The measuring happens elsewhere: resume_doc.problems (structure),
numbers.check_numbers (provenance) and compile (pages, widths, glyphs). Each
failure says what is wrong and what to do, because it goes straight into the
repair request and, if the repair also fails, to the person.
"""

import math
from dataclasses import dataclass, field

from resume_maxer.checks import FIT_RATIO, UNDERFILL_LINES, empty_lines, overflowing
from resume_maxer.compile import CompileResult, LineWidth
from resume_maxer.numbers import check_numbers
from resume_maxer.resume_doc import ResumeDoc, problems
from resume_maxer.schema import Master
from resume_maxer.skills import unbacked_parts, vocabulary


@dataclass(frozen=True)
class Review:
    failures: list[str]  # must be fixed: each one fails the resume
    flags: list[str]  # shown for review, never retried
    # Worth one repair, but never fail the resume, and outweighed by any failure:
    # an under-filled page beats one that a repair pushed onto two pages.
    shortfalls: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def check_document(doc: ResumeDoc, master: Master) -> Review:
    """Everything decidable before compiling: structure, skills and number provenance."""
    failures = problems(doc, master)
    vocab = vocabulary(master)
    for line in doc.skills:
        for item in line.items:
            failures += [
                f"skills line {line.label!r} item {item!r}: {why}; use a master skill name "
                "or alias, or drop it"
                for why in unbacked_parts(item, vocab)
            ]
    flags = []
    tech = master.tech_names()
    by_id = {b.id: b for e in master.entries for b in e.bullets}
    for key, _, bullet in doc.keyed_bullets():
        # Unknown sources are already structure failures; skip them here.
        metric_ids = {m for s in bullet.source_ids if s in by_id for m in by_id[s].metrics}
        result = check_numbers(bullet.text, [master.metrics[m].text for m in metric_ids], tech)
        failures += [f"{key} {bullet.text!r}: {f}" for f in result.failures]
        flags += [f"{key} {bullet.text!r}: {f}" for f in result.flags]
    return Review(failures, flags)


def chars_to_cut(text: str, ratio: float, fit_ratio: float = FIT_RATIO) -> int:
    """How many characters to remove so `text` fits, at its average character width."""
    # round() first: float noise turns an exact 10.0 into 10.000000000000002,
    # which ceil() would report as 11.
    return max(1, math.ceil(round(len(text) * (1 - fit_ratio / ratio), 6)))


def _overflow_message(width: LineWidth, doc: ResumeDoc) -> str:
    bullets = {key: bullet.text for key, _, bullet in doc.keyed_bullets()}
    if width.key in bullets:
        what, text = width.key, bullets[width.key]
    else:  # "skills.N", numbered from 1 like the template's loop.index
        line = doc.skills[int(width.key.removeprefix("skills.")) - 1]
        what = f"skills line {line.label!r}"
        text = f"{line.label}: {', '.join(line.items)}"
    return (
        f"{what} uses {width.ratio:.0%} of the line (at most {FIT_RATIO:.0%} fits): "
        f"cut at least {chars_to_cut(text, width.ratio)} characters from {text!r}"
    )


def review(doc: ResumeDoc, master: Master, compiled: CompileResult | None) -> Review:
    """The full verdict. `compiled` is None when the document could not be rendered."""
    found = check_document(doc, master)
    failures, shortfalls = list(found.failures), []
    if compiled is not None:
        empty = empty_lines(compiled)
        if empty is not None and empty >= UNDERFILL_LINES:
            shortfalls.append(
                f"the page has about {empty:.0f} empty lines at the bottom: add one or two "
                "relevant bullets, or a short entry, keeping every line to one line"
            )
        if compiled.pages != 1:
            failures.append(
                f"the resume is {compiled.pages} pages; it must be 1: drop the least "
                "relevant bullets or a whole entry"
            )
        failures += [_overflow_message(w, doc) for w in overflowing(compiled.widths)]
        failures += [
            f"the font has no glyph for {g}; replace that character"
            for g in compiled.missing_glyphs
        ]
    return Review(failures, found.flags, shortfalls)
