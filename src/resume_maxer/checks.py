"""Policy applied to what compile measured: what counts as a passing page."""

from io import BytesIO

from pypdf import PdfReader

from resume_maxer.compile import CompileResult, LineWidth

# A bullet or skills line must use at most 99% of the line, a small margin so a
# line that fits by a hair does not wrap after a one-character rewrite elsewhere.
FIT_RATIO = 0.99

# One bullet line's height in the template: 11.3pt line spacing plus 1.3pt after.
BULLET_LINE_PT = 12.6
# Empty space at the bottom, in bullet lines, from which a page counts as
# under-filled. The preferred resume leaves about 1.6; 3 is room for real content.
UNDERFILL_LINES = 3.0


def overflowing(widths: list[LineWidth], fit_ratio: float = FIT_RATIO) -> list[LineWidth]:
    return [w for w in widths if w.ratio > fit_ratio]


def empty_lines(compiled: CompileResult) -> float | None:
    """Bullet lines of unused space below the text; None unless it is one measured page."""
    if compiled.pages != 1 or compiled.used_pt is None or compiled.page_pt is None:
        return None
    # round(): float noise would put an exact 3.0 at 2.9999999999999996, under the line.
    return round((compiled.page_pt - compiled.used_pt) / BULLET_LINE_PT, 6)


def pdf_text(pdf: bytes) -> str:
    """The text an ATS would extract, read the same way a parser would."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
