"""Golden test: the preferred resume (file 05), rebuilt from data, must pass every check.

Reads personal data from the gitignored data/ folder at runtime, so nothing
personal is committed. Skips where that data or Tectonic is absent (always in CI).
"""

import json
import re
from pathlib import Path

import pytest

from resume_maxer.checks import UNDERFILL_LINES, empty_lines, overflowing, pdf_text
from resume_maxer.compile import compile_tex
from resume_maxer.load import load_master
from resume_maxer.render import render
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import check_document

DATA = Path("data")
MASTER = DATA / "master.json"
GOLDEN = DATA / "golden_05.json"
OUT = Path("out")

pytestmark = pytest.mark.skipif(
    not (MASTER.exists() and GOLDEN.exists()), reason="personal data/ files not present"
)


def _plain(text: str) -> str:
    # Typographic apostrophes and line wrapping are the only expected changes.
    return re.sub(r"\s+", " ", text.replace("’", "'"))


@pytest.fixture(scope="module")
def golden():
    master = load_master(MASTER)
    doc = ResumeDoc.model_validate(json.loads(GOLDEN.read_text(encoding="utf-8")))
    return master, doc


@pytest.fixture(scope="module")
def compiled(golden, tectonic):
    master, doc = golden
    result = compile_tex(render(doc, master))
    OUT.mkdir(exist_ok=True)
    (OUT / "golden_05.pdf").write_bytes(result.pdf)  # for the side-by-side review
    return result


def test_golden_document_passes_structure_and_number_checks(golden):
    master, doc = golden
    assert check_document(doc, master).failures == []


def test_one_page_no_missing_glyphs(compiled):
    assert compiled.pages == 1
    assert compiled.missing_glyphs == []


def test_preferred_resume_is_not_under_filled(compiled):
    # The reference for "full": its gap sets how much empty space is normal.
    assert empty_lines(compiled) < UNDERFILL_LINES


def test_every_bullet_and_skills_line_fits_one_line(golden, compiled):
    _, doc = golden
    bullets = sum(len(e.bullets) for e in doc.experience + doc.projects)
    assert len(compiled.widths) == bullets + len(doc.skills)
    assert [(w.key, f"{w.ratio:.1%}") for w in overflowing(compiled.widths)] == []


def test_ats_text_has_every_line_in_order(golden, compiled):
    master, doc = golden
    text = _plain(pdf_text(compiled.pdf))
    expected = [master.contact.name, "Education", "Technical Skills", "Experience", "Projects"]
    expected += [_plain(b.text) for e in doc.experience + doc.projects for b in e.bullets]
    positions = [text.find(s) for s in expected]
    missing = [s for s, p in zip(expected, positions, strict=True) if p < 0]
    assert missing == []
    assert positions[:5] == sorted(positions[:5])  # name, then sections in order
    assert "(cid:" not in text


def test_corrections_over_file_05_are_visible(golden, compiled):
    # Expectations come from data/ at runtime: real details never live in tests.
    master, doc = golden
    text = _plain(pdf_text(compiled.pdf))
    # P1: file 05 printed every "~N" estimate as "N".
    estimates = {
        m
        for e in doc.experience + doc.projects
        for b in e.bullets
        for m in re.findall(r"~[\d,]+[KkMm]?", b.text)
    }
    assert estimates and all(t in text for t in estimates)
    # P2: file 05 linked the wrong GitHub account; the header must show the data's links.
    assert all(link.label in text for link in master.contact.links if link.status == "CURRENT")
