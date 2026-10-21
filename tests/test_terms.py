"""The term flag: posting words a bullet uses that its own facts never mention."""

import pytest

from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import check_document
from resume_maxer.schema import Master
from resume_maxer.terms import backing_text, borrowed_terms, words

POSTING = (
    "We work agile, ship continuous integration pipelines, and build dashboards for "
    "field testers. Kubernetes and stakeholder management are a plus."
)


@pytest.fixture
def master(sample_data) -> Master:
    return Master.model_validate(sample_data)


def borrowed(master, sample_doc_data, text, bullet=0):
    sample_doc_data["experience"][0]["bullets"][bullet]["text"] = text
    sample_doc_data["experience"][0]["bullets"][bullet]["bold"] = []
    doc = ResumeDoc.model_validate(sample_doc_data)
    _, entry, b = doc.keyed_bullets()[bullet]
    return borrowed_terms(b.text, backing_text(entry, b, master), words(POSTING))


def test_planted_posting_word_is_flagged(master, sample_doc_data):
    text = "Shipped an agile fleet-monitoring dashboard to ~40 field testers"
    assert borrowed(master, sample_doc_data, text) == ["agile"]


def test_several_planted_words_are_all_listed(master, sample_doc_data):
    text = "Shipped dashboards to ~40 field testers through stakeholder management"
    assert borrowed(master, sample_doc_data, text) == ["stakeholder", "management"]


def test_posting_words_the_facts_use_are_not_flagged(master, sample_doc_data):
    # "dashboards", "field", "testers": all in the cited fact's wording and tags.
    assert borrowed(master, sample_doc_data, "Built dashboards for ~40 field testers") == []


def test_unbacked_words_not_from_the_posting_are_not_this_flags_job(master, sample_doc_data):
    # "telemetry" is unbacked but not borrowed; the writer's own phrasing is not flagged.
    assert borrowed(master, sample_doc_data, "Shipped telemetry dashboards to field testers") == []


def test_a_skill_named_in_the_facts_backs_its_aliases(master, sample_doc_data):
    # ACME-2 is tagged "CI/CD"; the master lists "continuous integration" as its alias.
    text = "Added continuous integration checks that block merges"
    assert borrowed(master, sample_doc_data, text, bullet=1) == []
    # The other polarity: the same words on a fact without that tag are flagged.
    assert borrowed(master, sample_doc_data, text, bullet=0) == ["continuous", "integration"]


def test_common_words_are_never_flagged():
    assert words("We build tools and systems for teams using technologies") == []
    # Regression: a real server run flagged "move" from "you'll move fast".
    assert words("You will move fast and learn quickly") == ["learn"]


def test_review_reports_borrowed_terms_as_flags_never_failures(master, sample_doc_data):
    sample_doc_data["experience"][0]["bullets"][0]["text"] = "Shipped agile dashboards"
    sample_doc_data["experience"][0]["bullets"][0]["bold"] = []
    doc = ResumeDoc.model_validate(sample_doc_data)
    result = check_document(doc, master, POSTING)
    assert result.failures == []
    assert result.flags == [
        "ACME.1 'Shipped agile dashboards': uses 'agile' from the posting, which its "
        "facts never mention; keep only if true"
    ]
    # Without a posting (as in `build`) there is nothing to compare against.
    assert check_document(doc, master).flags == []
