"""Integration tests: these compile real PDFs with Tectonic."""

import pytest

from resume_maxer.checks import overflowing, pdf_text
from resume_maxer.compile import CompileError, compile_tex, find_tectonic
from resume_maxer.render import render
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.schema import Master


def compile_doc(sample_data, doc_data):
    master = Master.model_validate(sample_data)
    return compile_tex(render(ResumeDoc.model_validate(doc_data), master))


def set_first_bullet(doc_data, text):
    doc_data["experience"][0]["bullets"][0] = {"source_ids": ["ACME-1"], "text": text, "bold": []}


def test_sample_compiles_to_one_clean_page(tectonic, sample_data, sample_doc_data):
    result = compile_doc(sample_data, sample_doc_data)
    assert result.pages == 1
    assert result.missing_glyphs == []
    keys = ["skills.1", "skills.2", "ACME.1", "ACME.2", "NWL.1", "WTHR.1", "WTHR.2"]
    assert [w.key for w in result.widths] == keys
    assert overflowing(result.widths) == []


def test_overlong_skills_line_is_measured_as_overflowing(tectonic, sample_data, sample_doc_data):
    # Regression: only bullets were measured, so a skills line that wrapped to a
    # second line went unnoticed and pushed a real resume onto two pages.
    sample_doc_data["skills"][1]["items"] = ["PostgreSQL", "Kubernetes", "CI/CD"] * 8
    result = compile_doc(sample_data, sample_doc_data)
    assert [w.key for w in overflowing(result.widths)] == ["skills.2"]


def test_overlong_bullet_is_measured_as_overflowing(tectonic, sample_data, sample_doc_data):
    long = "Built a fleet-monitoring dashboard with alerting, history, and exports " * 3
    set_first_bullet(sample_doc_data, long)
    result = compile_doc(sample_data, sample_doc_data)
    [over] = overflowing(result.widths)
    assert over.key == "ACME.1"
    assert over.ratio > 1
    # The ordinary bullets beside it still fit.
    assert all(w.ratio < 1 for w in result.widths if w.key != "ACME.1")


def test_missing_glyph_is_reported(tectonic, sample_data, sample_doc_data):
    set_first_bullet(sample_doc_data, "Built a snowman ☃ tracker")
    result = compile_doc(sample_data, sample_doc_data)
    assert result.missing_glyphs == ["☃ (U+2603)"]


def test_characters_the_data_uses_are_in_the_font(tectonic, sample_data, sample_doc_data):
    set_first_bullet(sample_doc_data, "Wander → Seek, Aug – May, Dean’s, ~10")
    assert compile_doc(sample_data, sample_doc_data).missing_glyphs == []


def test_ats_text_keeps_tilde_and_plain_ligature_letters(tectonic, sample_data, sample_doc_data):
    set_first_bullet(sample_doc_data, "Profiled files and workflows for ~40 field testers")
    text = pdf_text(compile_doc(sample_data, sample_doc_data).pdf)
    # P1: ~ survives; spike: "fi"/"fl" extract as letters, not ligature glyphs.
    assert "Profiled files and workflows for ~40 field testers" in text
    assert "ﬁ" not in text and "ﬂ" not in text


def test_latex_in_text_is_printed_not_run(tectonic, sample_data, sample_doc_data):
    set_first_bullet(sample_doc_data, r"Ran \input{/etc/passwd} safely")
    text = pdf_text(compile_doc(sample_data, sample_doc_data).pdf)
    assert r"Ran \input{/etc/passwd} safely" in text


def test_compile_failure_surfaces_the_error(tectonic):
    with pytest.raises(CompileError, match="Tectonic failed"):
        compile_tex(r"\documentclass{article}\begin{document}\undefinedmacro\end{document}")


def test_misconfigured_tectonic_path_says_how_to_fix(monkeypatch, tmp_path):
    monkeypatch.setenv("TECTONIC", str(tmp_path / "nope.exe"))
    with pytest.raises(CompileError, match="TECTONIC is set to"):
        find_tectonic()
