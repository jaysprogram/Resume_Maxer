import json
from pathlib import Path

import pytest

from resume_maxer.load import MASTER_FILENAME, MasterDataError, load_master

REAL_MASTER = Path("data") / MASTER_FILENAME


def test_loads_sample_by_path(sample_path):
    assert load_master(sample_path).contact.name == "Alex Rivera"


def test_reads_from_resume_data_dir(tmp_path, monkeypatch, sample_data):
    (tmp_path / MASTER_FILENAME).write_text(json.dumps(sample_data), encoding="utf-8")
    monkeypatch.setenv("RESUME_DATA_DIR", str(tmp_path))
    assert load_master().contact.name == "Alex Rivera"


def test_missing_file_says_where_it_looked_and_how_to_fix(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_DATA_DIR", str(tmp_path))
    with pytest.raises(MasterDataError) as exc:
        load_master()
    message = str(exc.value)
    assert str(tmp_path / MASTER_FILENAME) in message
    assert "RESUME_DATA_DIR" in message
    assert "examples/sample_master.json" in message


def test_malformed_json_reports_line(tmp_path):
    path = tmp_path / MASTER_FILENAME
    path.write_text('{\n  "contact": {},\n}\n', encoding="utf-8")
    with pytest.raises(MasterDataError, match=r"not valid JSON \(line 3"):
        load_master(path)


def test_duplicate_json_key_is_rejected(tmp_path, sample_data):
    # Plain json.loads would keep the second NWL-M1 and silently drop the first.
    path = tmp_path / MASTER_FILENAME
    text = json.dumps(sample_data).replace(
        '"NWL-M1":', '"NWL-M1": {"text": "first", "status": "CURRENT"}, "NWL-M1":', 1
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MasterDataError, match="duplicate key 'NWL-M1'"):
        load_master(path)


def test_validation_error_names_the_file(tmp_path, sample_data):
    sample_data["entries"][0]["bullets"][0]["metrics"] = ["MISSING-M1"]
    path = tmp_path / MASTER_FILENAME
    path.write_text(json.dumps(sample_data), encoding="utf-8")
    with pytest.raises(MasterDataError, match="failed validation") as exc:
        load_master(path)
    assert "MISSING-M1" in str(exc.value)


@pytest.mark.skipif(not REAL_MASTER.exists(), reason="no personal data/master.json here")
def test_sample_contains_none_of_the_real_contact_details(sample_path):
    # Reads personal data at runtime from the gitignored data/ folder, so the
    # real values never appear in the repo. Skipped in CI.
    real = load_master(REAL_MASTER).contact
    sample_text = sample_path.read_text(encoding="utf-8")
    values = [real.name, real.email, *(link.url for link in real.links)]
    leaked = [v for v in values if v and v in sample_text]
    assert leaked == []
