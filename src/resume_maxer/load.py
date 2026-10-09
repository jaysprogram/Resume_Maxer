"""Load master data from outside git, failing with a message that says what to fix."""

import json
import os
from pathlib import Path

from pydantic import ValidationError

from resume_maxer.schema import Master

DATA_DIR_ENV = "RESUME_DATA_DIR"
DEFAULT_DATA_DIR = Path("data")
MASTER_FILENAME = "master.json"


class MasterDataError(Exception):
    """The master data file is missing, malformed, or inconsistent."""


def data_dir() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV, DEFAULT_DATA_DIR))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # json.loads keeps the last of two identical keys without complaint, so a
    # copy-pasted metric ID would silently replace the first metric's text.
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise MasterDataError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def load_master(path: Path | None = None) -> Master:
    path = path or data_dir() / MASTER_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise MasterDataError(
            f"No master data at {path}. Create it (format: examples/sample_master.json) "
            f"or set {DATA_DIR_ENV} to the folder that holds {MASTER_FILENAME}."
        ) from None

    try:
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as e:
        raise MasterDataError(
            f"{path} is not valid JSON (line {e.lineno}, column {e.colno}): {e.msg}"
        ) from None
    except MasterDataError as e:
        raise MasterDataError(f"{path}: {e}") from None

    try:
        return Master.model_validate(data)
    except ValidationError as e:
        raise MasterDataError(f"{path} failed validation:\n{e}") from None
