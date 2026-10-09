import pytest
from pydantic import ValidationError

from resume_maxer.schema import SELECTABLE, Master


def _bullet(data: dict, bullet_id: str) -> dict:
    return next(b for e in data["entries"] for b in e["bullets"] if b["id"] == bullet_id)


def test_sample_master_loads(sample_data):
    master = Master.model_validate(sample_data)
    assert [e.id for e in master.entries] == ["ACME", "NWL", "CLUB", "WTHR"]
    assert _bullet(sample_data, "ACME-1")["metrics"] == ["ACME-M1", "ACME-M2"]
    assert master.metrics["NWL-M1"].notes == ["Hours, not dollars"]


def test_valid_metric_reference_loads(sample_data):
    _bullet(sample_data, "ACME-2")["metrics"] = ["ACME-M2"]
    Master.model_validate(sample_data)


def test_unknown_metric_reference_fails(sample_data):
    _bullet(sample_data, "ACME-1")["metrics"].append("ACME-M90")
    with pytest.raises(
        ValidationError, match="bullet 'ACME-1' references unknown metric 'ACME-M90'"
    ):
        Master.model_validate(sample_data)


def test_unknown_skill_evidence_fails(sample_data):
    sample_data["skills"][0]["evidence"].append("NOPE-1")
    with pytest.raises(ValidationError, match="skill 'Python' cites unknown evidence 'NOPE-1'"):
        Master.model_validate(sample_data)


def test_skill_evidence_may_cite_an_entry_or_a_bullet(sample_data):
    sample_data["skills"][0]["evidence"] = ["NWL", "WTHR-1"]
    Master.model_validate(sample_data)


def test_unknown_conflicts_with_fails(sample_data):
    _bullet(sample_data, "WTHR-1")["variants"]["detailed"]["conflicts_with"] = ["WTHR-9"]
    with pytest.raises(ValidationError, match="conflicts with unknown bullet 'WTHR-9'"):
        Master.model_validate(sample_data)


def test_duplicate_bullet_id_fails(sample_data):
    _bullet(sample_data, "WTHR-2")["id"] = "ACME-1"
    with pytest.raises(ValidationError, match="ID 'ACME-1' is used more than once"):
        Master.model_validate(sample_data)


def test_entry_and_bullet_ids_share_one_namespace(sample_data):
    # Skill evidence can cite either, so an entry and a bullet must not collide.
    _bullet(sample_data, "WTHR-2")["id"] = "NWL"
    with pytest.raises(ValidationError, match="ID 'NWL' is used more than once"):
        Master.model_validate(sample_data)


def test_all_problems_reported_together(sample_data):
    _bullet(sample_data, "ACME-1")["metrics"].append("ACME-M90")
    sample_data["skills"][0]["evidence"].append("NOPE-1")
    with pytest.raises(ValidationError) as exc:
        Master.model_validate(sample_data)
    assert "ACME-M90" in str(exc.value)
    assert "NOPE-1" in str(exc.value)


def test_misspelled_status_fails(sample_data):
    _bullet(sample_data, "ACME-1")["status"] = "CURENT"
    with pytest.raises(ValidationError, match="status"):
        Master.model_validate(sample_data)


def test_misspelled_field_name_fails(sample_data):
    bullet = _bullet(sample_data, "ACME-1")
    bullet["metrcis"] = bullet.pop("metrics")
    with pytest.raises(ValidationError, match="metrcis"):
        Master.model_validate(sample_data)


def test_bullet_needs_at_least_one_variant(sample_data):
    _bullet(sample_data, "ACME-2")["variants"] = {}
    with pytest.raises(ValidationError, match="variants"):
        Master.model_validate(sample_data)


def test_invalid_items_load_but_are_not_selectable(sample_data):
    master = Master.model_validate(sample_data)
    all_ids = {b.id for e in master.entries for b in e.bullets}
    selectable = {b.id for _, b in master.selectable_bullets()}

    # Present in the data, so the record of "never use this" survives...
    assert {"ACME-3", "NWL-2", "CLUB-1"} <= all_ids
    # ...but never offered: INVALID bullet, UNVERIFIED bullet, bullet in an INVALID entry.
    assert selectable.isdisjoint({"ACME-3", "NWL-2", "CLUB-1"})
    # The ordinary cases still get through, ARCHIVED included.
    assert selectable == {"ACME-1", "ACME-2", "NWL-1", "WTHR-1", "WTHR-2"}


def test_selectable_policy():
    assert SELECTABLE == {"CURRENT", "ARCHIVED", "DEFENSIBLE ESTIMATE", "QUALITATIVE ONLY"}
