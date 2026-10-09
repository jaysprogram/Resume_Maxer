import pytest

from resume_maxer.render import RenderError, bolded, render, url
from resume_maxer.resume_doc import ResumeDoc, problems
from resume_maxer.schema import Master


@pytest.fixture
def master(sample_data) -> Master:
    return Master.model_validate(sample_data)


def doc_from(data: dict) -> ResumeDoc:
    return ResumeDoc.model_validate(data)


# --- bolded: escaping plus bold, with no hand-written \textbf ---------------


def test_bold_phrase_is_escaped_and_wrapped():
    assert bolded("Saved ~12 hours & more", ["~12 hours"]) == (
        r"Saved \textbf{\textasciitilde{}12 hours} \& more"
    )


def test_several_bold_phrases_in_text_order():
    assert bolded("Built C# tools for 50% of R&D", ["50%", "C#"]) == (
        r"Built \textbf{C\#} tools for \textbf{50\%} of R\&D"
    )


def test_no_bold_still_escapes():
    assert bolded("R&D", []) == r"R\&D"


@pytest.mark.parametrize(
    ("phrases", "message"),
    [(["missing"], "is not in"), ([""], "is not in"), (["Built a", "a dash"], "overlap")],
)
def test_bad_bold_phrases_fail(phrases, message):
    with pytest.raises(RenderError, match=message):
        bolded("Built a dashboard", phrases)


# --- url: hyperref takes URLs nearly verbatim -------------------------------


@pytest.mark.parametrize("value", ["https://code.example.com/alex", "mailto:a.b@example.com"])
def test_plain_urls_pass(value):
    assert url(value) == value


@pytest.mark.parametrize(
    "value", ["https://example.com/a%20b", "https://example.com/}\\input{x}", "javascript:alert(1)"]
)
def test_urls_with_latex_specials_or_odd_schemes_fail(value):
    with pytest.raises(RenderError):
        url(value)


# --- problems: the document must be backed by the master --------------------


def test_sample_doc_has_no_problems(master, sample_doc_data):
    assert problems(doc_from(sample_doc_data), master) == []


def test_unknown_entry(master, sample_doc_data):
    sample_doc_data["experience"][0]["entry_id"] = "NOPE"
    assert problems(doc_from(sample_doc_data), master) == ["unknown entry 'NOPE'"]


def test_invalid_entry(master, sample_doc_data):
    sample_doc_data["experience"].append({"entry_id": "CLUB", "bullets": []})
    assert "entry 'CLUB' is INVALID" in problems(doc_from(sample_doc_data), master)


def test_project_in_experience_section(master, sample_doc_data):
    sample_doc_data["experience"].append({"entry_id": "WTHR", "bullets": []})
    assert "entry 'WTHR' is a project, not allowed in experience" in problems(
        doc_from(sample_doc_data), master
    )


def test_stack_item_not_in_master(master, sample_doc_data):
    sample_doc_data["projects"][0]["stack"].append("Rust")
    assert problems(doc_from(sample_doc_data), master) == [
        "entry 'WTHR' stack item 'Rust' is not in its master stack"
    ]


def test_bullet_citing_another_entrys_fact(master, sample_doc_data):
    sample_doc_data["experience"][0]["bullets"][0]["source_ids"] = ["WTHR-1"]
    assert problems(doc_from(sample_doc_data), master) == [
        "entry 'ACME' bullet cites 'WTHR-1', not one of its own"
    ]


def test_bullet_citing_an_invalid_fact(master, sample_doc_data):
    sample_doc_data["experience"][0]["bullets"][0]["source_ids"] = ["ACME-3"]
    assert problems(doc_from(sample_doc_data), master) == [
        "entry 'ACME' bullet cites 'ACME-3', which is INVALID"
    ]


def test_unknown_credential(master, sample_doc_data):
    sample_doc_data["credentials"] = ["CRED-9"]
    assert problems(doc_from(sample_doc_data), master) == ["unknown credential 'CRED-9'"]


# --- render ------------------------------------------------------------------


def test_render_refuses_a_document_with_problems(master, sample_doc_data):
    sample_doc_data["experience"][0]["entry_id"] = "NOPE"
    with pytest.raises(RenderError, match="unknown entry 'NOPE'"):
        render(doc_from(sample_doc_data), master)


def test_rendered_sample(master, sample_doc_data):
    tex = render(doc_from(sample_doc_data), master)

    assert r"\VAR{" not in tex and r"\BLOCK{" not in tex
    sections = [
        tex.index(rf"\section{{{s}}}")
        for s in ("Education", "Technical Skills", "Experience", "Projects")
    ]
    assert sections == sorted(sections)
    assert r"\resumeBullet{ACME.1}{Shipped a fleet-monitoring dashboard to " in tex
    assert r"\textbf{\textasciitilde{}40 field testers}" in tex
    assert r"reconciliation \& reporting" in tex
    assert r"\href{mailto:alex.rivera@example.com}{alex.rivera@example.com} $|$ " in tex
    assert r"\project{Weather Dashboard $|$ Go 1.22, React}" in tex
    assert "Example Safety Certification" in tex


def test_unverified_contact_link_and_gpa_are_left_off(master, sample_doc_data):
    tex = render(doc_from(sample_doc_data), master)
    assert "profile.example.com" not in tex  # UNVERIFIED link
    assert "GPA" not in tex  # UNVERIFIED GPA
    assert "code.example.com/alex" in tex  # the CURRENT link still shows


def test_text_that_looks_like_latex_is_printed_not_run(master, sample_doc_data):
    sample_doc_data["experience"][0]["bullets"][0] = {
        "source_ids": ["ACME-1"],
        "text": r"Ran \input{/etc/passwd} and \write18{rm -rf /}",
        "bold": [],
    }
    tex = render(doc_from(sample_doc_data), master)
    assert r"\textbackslash{}input\{/etc/passwd\}" in tex
    assert r"\input{/etc/passwd}" not in tex
