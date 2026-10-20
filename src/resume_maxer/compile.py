"""Compile LaTeX with Tectonic in a throwaway folder and read back what LaTeX measured."""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

TECTONIC_ENV = "TECTONIC"
# Generous because Tectonic downloads missing packages on its first run.
DEFAULT_TIMEOUT_S = 180

_WIDTH = re.compile(r"^LINEWIDTH (\S+) ([\d.]+)pt ([\d.]+)pt$", re.MULTILINE)
# Only the character and its code point: TeX wraps log lines at 79 columns,
# which cuts the font name that follows mid-word.
_MISSING = re.compile(r"^Missing character: There is no (.+?) in font", re.MULTILINE)


class CompileError(RuntimeError):
    """Tectonic is missing, failed, or timed out."""


@dataclass(frozen=True)
class LineWidth:
    key: str  # a bullet's entry ID and position ("NEE.2"), or a skills line ("skills.1")
    width_pt: float  # typeset width of the line's text
    available_pt: float  # width the text may use (a bullet's excludes its marker box)

    @property
    def ratio(self) -> float:
        return self.width_pt / self.available_pt


@dataclass(frozen=True)
class CompileResult:
    pdf: bytes
    pages: int
    widths: list[LineWidth]
    missing_glyphs: list[str]
    log: str


def find_tectonic() -> str:
    configured = os.environ.get(TECTONIC_ENV)
    if configured:
        if not Path(configured).is_file():
            raise CompileError(f"{TECTONIC_ENV} is set to {configured!r}, which does not exist.")
        return configured
    found = shutil.which("tectonic")
    if found:
        return found
    raise CompileError(
        "Tectonic not found. Install it (https://tectonic-typesetting.github.io) and put it "
        f"on PATH, or set {TECTONIC_ENV} to the executable's full path."
    )


def _tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def compile_tex(tex: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> CompileResult:
    exe = find_tectonic()
    with tempfile.TemporaryDirectory(prefix="resume-maxer-") as tmp:
        src = Path(tmp) / "resume.tex"
        src.write_text(tex, encoding="utf-8")
        # Argument list, never a shell string. --untrusted disables shell-escape
        # and every other feature Tectonic knows to be unsafe on untrusted input.
        cmd = [exe, "--untrusted", "--keep-logs", "--outdir", tmp, str(src)]
        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise CompileError(f"Tectonic did not finish within {timeout_s}s.") from None

        log_path = Path(tmp) / "resume.log"
        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        if proc.returncode != 0:
            raise CompileError("Tectonic failed:\n" + _tail(proc.stderr or log))
        pdf = (Path(tmp) / "resume.pdf").read_bytes()

    widths = [LineWidth(k, float(w), float(a)) for k, w, a in _WIDTH.findall(log)]
    missing = sorted(set(_MISSING.findall(log)))
    pages = len(PdfReader(BytesIO(pdf)).pages)
    return CompileResult(pdf=pdf, pages=pages, widths=widths, missing_glyphs=missing, log=log)
