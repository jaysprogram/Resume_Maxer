"""Tailor runs for the web app: one folder per run, worked one at a time.

A run takes minutes, longer than a phone keeps a request open, so the web app
queues it here and the run page polls its status. Everything a run produces
lives in its folder (posting, status, PDF, resume document), so finished runs
survive restarts; a run cut off by a restart is marked interrupted, never left
looking busy forever.
"""

import os
import re
import secrets
import traceback
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from resume_maxer.pipeline import Tailored

RUN_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_POSTING_CHARS = 50_000
_LABEL_CHARS = re.compile(r"[^A-Za-z0-9 ._-]+")

State = Literal["queued", "running", "done", "error", "interrupted"]


class PostingError(ValueError):
    """The submitted job description is empty or too long."""


class VerdictView(BaseModel):
    score: int
    summary: str
    gaps: list[str]


class RunStatus(BaseModel):
    id: str
    label: str
    state: State
    created: str
    finished: str | None = None
    passed: bool | None = None
    failures: list[str] = []
    shortfalls: list[str] = []
    flags: list[str] = []
    verdict: VerdictView | None = None
    judge_note: str | None = None
    cost_usd: float | None = None
    error: str | None = None
    has_pdf: bool = False

    @property
    def pending(self) -> bool:
        return self.state in ("queued", "running")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_label(label: str) -> str:
    """A run name safe to show and to use in a download file name."""
    cleaned = " ".join(_LABEL_CHARS.sub(" ", label).split()).strip(" .")[:60].strip()
    return cleaned or "resume"


class RunStore:
    def __init__(self, root: Path, tailor_fn: Callable[[str], Tailored]):
        self.root = root
        self.tailor_fn = tailor_fn
        root.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tailor")
        self._futures: list[Future] = []
        for status in self.list(limit=None):
            if status.pending:  # cut off by the last shutdown
                self._save(status.model_copy(update={"state": "interrupted", "finished": _now()}))

    def _dir(self, run_id: str) -> Path | None:
        # The id comes from a URL: only exact 32-hex names, so no path can escape root.
        return self.root / run_id if RUN_ID.fullmatch(run_id) else None

    def _save(self, status: RunStatus) -> None:
        folder = self.root / status.id
        tmp = folder / "status.json.tmp"
        tmp.write_text(status.model_dump_json(indent=1), encoding="utf-8")
        os.replace(tmp, folder / "status.json")  # readers never see a half-written file

    def create(self, posting: str, label: str = "") -> RunStatus:
        posting = posting.strip()
        if not posting:
            raise PostingError("the job description is empty")
        if len(posting) > MAX_POSTING_CHARS:
            raise PostingError(
                f"the job description is {len(posting):,} characters; the limit is "
                f"{MAX_POSTING_CHARS:,}"
            )
        run_id = secrets.token_hex(16)
        folder = self.root / run_id
        folder.mkdir()
        (folder / "posting.txt").write_text(posting, encoding="utf-8")
        status = RunStatus(id=run_id, label=clean_label(label), state="queued", created=_now())
        self._save(status)
        self._futures.append(self._executor.submit(self._work, run_id))
        return status

    def get(self, run_id: str) -> RunStatus | None:
        folder = self._dir(run_id)
        if folder is None or not (folder / "status.json").is_file():
            return None
        return RunStatus.model_validate_json((folder / "status.json").read_text("utf-8"))

    def list(self, limit: int | None = 20) -> list[RunStatus]:
        runs = [self.get(p.name) for p in self.root.iterdir() if p.is_dir()]
        runs = sorted((r for r in runs if r), key=lambda r: r.created, reverse=True)
        return runs[:limit] if limit else runs

    def pdf_path(self, run_id: str) -> Path | None:
        folder = self._dir(run_id)
        path = folder / "resume.pdf" if folder else None
        return path if path and path.is_file() else None

    def wait_idle(self) -> None:
        """Block until every queued run has finished."""
        wait(self._futures)

    def close(self) -> None:
        """Finish queued work and stop the worker (at shutdown)."""
        self._executor.shutdown(wait=True)

    def _work(self, run_id: str) -> None:
        status = self.get(run_id)
        self._save(status := status.model_copy(update={"state": "running"}))
        folder = self.root / run_id
        try:
            result = self.tailor_fn((folder / "posting.txt").read_text("utf-8"))
        except Exception as exc:  # any failure must reach the run page, never vanish
            message = str(exc) or type(exc).__name__
            (folder / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            self._save(
                status.model_copy(update={"state": "error", "error": message, "finished": _now()})
            )
            return
        (folder / "resume.json").write_text(result.doc.model_dump_json(indent=2), "utf-8")
        if result.pdf is not None:
            (folder / "resume.pdf").write_bytes(result.pdf)
        verdict = result.verdict
        self._save(
            status.model_copy(
                update={
                    "state": "done",
                    "finished": _now(),
                    "passed": result.passed,
                    "failures": result.failures,
                    "shortfalls": result.shortfalls,
                    "flags": result.flags,
                    "verdict": (
                        VerdictView(
                            score=verdict.score, summary=verdict.summary, gaps=verdict.top_gaps()
                        )
                        if verdict
                        else None
                    ),
                    "judge_note": result.judge_note,
                    "cost_usd": round(result.cost_usd, 4),
                    "has_pdf": result.pdf is not None,
                }
            )
        )
