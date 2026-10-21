"""Review: measured results become fixable failures. Pure: a fake compile result, no TeX."""

import pytest

from resume_maxer.compile import CompileResult, LineWidth
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import chars_to_cut, review
from resume_maxer.schema import Master


@pytest.fixture
def master(sample_data) -> Master:
    return Master.model_validate(sample_data)


def compiled(pages=1, widths=(), missing=()) -> CompileResult:
    return CompileResult(
        pdf=b"%PDF", pages=pages, widths=list(widths), missing_glyphs=list(missing), log=""
    )


def doc_with_first_bullet(sample_doc_data, text) -> ResumeDoc:
    sample_doc_data["experience"][0]["bullets"][0]["text"] = text
    sample_doc_data["experience"][0]["bullets"][0]["bold"] = []
    return ResumeDoc.model_validate(sample_doc_data)


def test_clean_document_passes(master, sample_doc_data):
    doc = ResumeDoc.model_validate(sample_doc_data)
    result = review(doc, master, compiled(widths=[LineWidth("ACME.1", 90.0, 100.0)]))
    assert result.passed
    assert result.failures == [] and result.flags == []


def test_number_without_its_estimate_marker_fails_naming_the_bullet(master, sample_doc_data):
    doc = doc_with_first_bullet(sample_doc_data, "Shipped a dashboard to 40 field testers")
    [failure] = review(doc, master, compiled()).failures
    assert failure.startswith("ACME.1 'Shipped a dashboard to 40 field testers': ")
    assert "'~40'" in failure  # tells the writer the right form


def test_changed_unit_word_is_a_flag_not_a_failure(master, sample_doc_data):
    doc = doc_with_first_bullet(sample_doc_data, "Shipped a dashboard to ~40 drivers")
    result = review(doc, master, compiled())
    assert result.passed
    [flag] = result.flags
    assert flag.startswith("ACME.1 ") and "'drivers'" in flag


def test_overflowing_bullet_says_how_much_to_cut(master, sample_doc_data):
    doc = ResumeDoc.model_validate(sample_doc_data)
    text = sample_doc_data["experience"][0]["bullets"][0]["text"]
    [failure] = review(doc, master, compiled(widths=[LineWidth("ACME.1", 103.0, 100.0)])).failures
    cut = chars_to_cut(text, 1.03)
    assert failure == (
        f"ACME.1 uses 103% of the line (at most 99% fits): "
        f"cut at least {cut} characters from {text!r}"
    )


def test_overflowing_skills_line_names_its_label(master, sample_doc_data):
    doc = ResumeDoc.model_validate(sample_doc_data)
    [failure] = review(doc, master, compiled(widths=[LineWidth("skills.2", 101.0, 100.0)])).failures
    assert failure.startswith("skills line 'Tools & Cloud' uses 101% of the line")
    assert "'Tools & Cloud: PostgreSQL, Kubernetes, CI/CD'" in failure


def test_two_pages_and_missing_glyphs_fail(master, sample_doc_data):
    doc = ResumeDoc.model_validate(sample_doc_data)
    failures = review(doc, master, compiled(pages=2, missing=["☃ (U+2603)"])).failures
    assert failures == [
        "the resume is 2 pages; it must be 1: drop the least relevant bullets or a whole entry",
        "the font has no glyph for ☃ (U+2603); replace that character",
    ]


def test_unrenderable_document_still_gets_its_structure_failures(master, sample_doc_data):
    sample_doc_data["experience"][0]["entry_id"] = "NOPE"
    doc = ResumeDoc.model_validate(sample_doc_data)
    assert review(doc, master, None).failures == ["unknown entry 'NOPE'"]


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [(1.10, 10), (1.0, 1), (0.995, 1)],  # always at least one character once over
)
def test_chars_to_cut(ratio, expected):
    assert chars_to_cut("x" * 100, ratio) == expected


# --- under-filled page: a shortfall, never a failure ----------------------------


def filled(empty_lines, pages=1) -> CompileResult:
    result = compiled(pages=pages)
    page = 731.4
    return CompileResult(
        **{**result.__dict__, "used_pt": page - empty_lines * 12.6, "page_pt": page}
    )


@pytest.mark.parametrize("lines", [3.0, 6.5])
def test_under_filled_page_is_a_shortfall_not_a_failure(master, sample_doc_data, lines):
    result = review(ResumeDoc.model_validate(sample_doc_data), master, filled(lines))
    assert result.passed  # a shortfall never fails the resume
    [shortfall] = result.shortfalls
    assert shortfall.startswith(f"the page has about {lines:.0f} empty lines at the bottom")


@pytest.mark.parametrize("lines", [0.6, 1.6, 2.9])  # 1.6 is the preferred resume's gap
def test_well_filled_page_has_no_shortfall(master, sample_doc_data, lines):
    assert review(ResumeDoc.model_validate(sample_doc_data), master, filled(lines)).shortfalls == []


def test_fill_is_not_judged_on_a_two_page_resume(master, sample_doc_data):
    result = review(ResumeDoc.model_validate(sample_doc_data), master, filled(10, pages=2))
    assert result.shortfalls == [] and "2 pages" in result.failures[0]
