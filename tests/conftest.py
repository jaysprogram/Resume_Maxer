import json
import os
from pathlib import Path

import pytest

from resume_maxer.compile import CompileError, find_tectonic

EXAMPLES = Path(__file__).parent.parent / "examples"
SAMPLE_MASTER = EXAMPLES / "sample_master.json"
SAMPLE_DOC = EXAMPLES / "sample_resume_doc.json"


@pytest.fixture(scope="session")
def tectonic() -> str:
    """For integration tests that compile real PDFs.

    Skips, with the reason, where Tectonic is not installed. In CI it fails
    instead: CI installs Tectonic, so a missing one means a broken install, and
    silently skipping would turn every compile test into a no-op.
    """
    try:
        return find_tectonic()
    except CompileError as e:
        if os.environ.get("CI"):
            pytest.fail(f"CI must have Tectonic: {e}")
        pytest.skip(str(e))


@pytest.fixture
def sample_path() -> Path:
    return SAMPLE_MASTER


@pytest.fixture
def sample_data() -> dict:
    """A fresh, mutable copy of the fictional sample master data."""
    return json.loads(SAMPLE_MASTER.read_text(encoding="utf-8"))


@pytest.fixture
def sample_doc_data() -> dict:
    """A fresh, mutable copy of the fictional sample resume document."""
    return json.loads(SAMPLE_DOC.read_text(encoding="utf-8"))
