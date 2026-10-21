"""Skills-line items must be backed by the master: names, aliases or a usable stack."""

import pytest

from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import check_document
from resume_maxer.schema import Master
from resume_maxer.skills import unbacked_parts, vocabulary


@pytest.fixture
def master(sample_data) -> Master:
    sample_data["skills"] += [
        {"name": "AWS", "category": "Cloud", "status": "CURRENT"},
        {"name": "AWS Lambda", "category": "Cloud", "status": "CURRENT"},
        {"name": ".NET", "category": "Frameworks", "status": "CURRENT", "aliases": ["ASP.NET"]},
        {"name": "Claude / LLM APIs", "category": "AI", "status": "CURRENT"},
    ]
    return Master.model_validate(sample_data)


@pytest.mark.parametrize(
    "item",
    [
        "Python",
        "golang",  # alias, any case
        "  Kubernetes ",  # spacing
        "k8s",
        "Go 1.22",  # a usable entry's stack item
        "React",
        "CI/CD",  # a name containing "/" is matched whole
        "Go / Python",
        "AWS (Lambda)",  # head plus part: "AWS Lambda"
        "Postgres (SQL)",
        ".NET (ASP.NET)",
        "LLM APIs",  # either side of "Claude / LLM APIs"
        # A writer run packed a whole line into one item; on the page it is the same.
        "Python, Go (Golang), CI/CD, Claude / LLM APIs",
    ],
)
def test_backed_items_pass(master, item):
    assert unbacked_parts(item, vocabulary(master)) == []


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ("Power BI", ["'Power BI' is not a skill in the master"]),
        # Regression: a real writer run printed "NET (ASP.NET)", dropping the dot.
        ("NET (ASP.NET)", ["'NET' is not a skill in the master"]),
        ("Rust", ["'Rust' is UNVERIFIED in the master"]),
        ("Go (Rust, Python)", ["'Rust' is UNVERIFIED in the master"]),
        ("AWS (Lambda, Glue)", ["'Glue' is not a skill in the master"]),
        ("Python / Excel", ["'Excel' is not a skill in the master"]),
        ("Python, Power BI, Go", ["'Power BI' is not a skill in the master"]),
    ],
)
def test_unbacked_parts_are_named(master, item, expected):
    assert unbacked_parts(item, vocabulary(master)) == expected


def test_stack_of_an_unusable_entry_does_not_count(sample_data):
    sample_data["entries"][2]["stack"] = ["Fortran"]  # CLUB, which is INVALID
    master = Master.model_validate(sample_data)
    assert unbacked_parts("Fortran", vocabulary(master)) == [
        "'Fortran' is not a skill in the master"
    ]


def test_review_fails_an_invented_skill_and_passes_the_sample(master, sample_doc_data):
    assert check_document(ResumeDoc.model_validate(sample_doc_data), master).failures == []
    sample_doc_data["skills"][1]["items"].append("Power BI")
    [failure] = check_document(ResumeDoc.model_validate(sample_doc_data), master).failures
    assert failure == (
        "skills line 'Tools & Cloud' item 'Power BI': 'Power BI' is not a skill in the "
        "master; use a master skill name or alias, or drop it"
    )
