import json
from pathlib import Path

import pytest

SAMPLE_MASTER = Path(__file__).parent.parent / "examples" / "sample_master.json"


@pytest.fixture
def sample_path() -> Path:
    return SAMPLE_MASTER


@pytest.fixture
def sample_data() -> dict:
    """A fresh, mutable copy of the fictional sample master data."""
    return json.loads(SAMPLE_MASTER.read_text(encoding="utf-8"))
