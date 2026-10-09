"""Policy applied to what compile measured: what counts as a passing page."""

from io import BytesIO

from pypdf import PdfReader

from resume_maxer.compile import BulletWidth

# A bullet must use at most 99% of the line, a small margin so a bullet that
# fits by a hair does not wrap after a one-character rewrite elsewhere.
FIT_RATIO = 0.99


def overflowing(widths: list[BulletWidth], fit_ratio: float = FIT_RATIO) -> list[BulletWidth]:
    return [w for w in widths if w.ratio > fit_ratio]


def pdf_text(pdf: bytes) -> str:
    """The text an ATS would extract, read the same way a parser would."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)
