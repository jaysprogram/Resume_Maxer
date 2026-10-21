"""Command line: tailor a resume to a job description, or rebuild an edited one.

  resume-maxer tailor JOB.txt          write, check, repair once; PDF + JSON in out/
  resume-maxer tailor -                read the job description from stdin
  resume-maxer build out/JOB.json      recompile and recheck a hand-edited document
  resume-maxer serve                   run the web app (see README "Web app")
  resume-maxer hash-password           make the web app's password hash and secret

Exit codes: 0 every check passed, 1 a PDF was written but checks still fail,
2 nothing usable was produced (the message says why).
"""

import argparse
import getpass
import os
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError

from resume_maxer.auth import hash_password
from resume_maxer.claude import ClaudeError, find_claude
from resume_maxer.compile import CompileError, find_tectonic
from resume_maxer.judge import JUDGES
from resume_maxer.load import MASTER_FILENAME, MasterDataError, data_dir, load_master
from resume_maxer.pipeline import Tailored, TailorError, check, tailor
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import Review
from resume_maxer.web import (
    BACKEND_ENV,
    PASSWORD_HASH_ENV,
    SECRET_ENV,
    ConfigError,
    WebConfig,
    create_app,
    tailor_with,
)
from resume_maxer.writer import BACKEND, BACKENDS

OUT_DIR = Path("out")
EXIT_PASSED, EXIT_FAILURES, EXIT_ERROR = 0, 1, 2


class UsageError(Exception):
    """Bad input from the person running the command."""


def _read_job(source: str) -> tuple[str, str]:
    """The job description text and a file stem to name outputs after."""
    if source == "-":
        text, stem = sys.stdin.read(), "resume"
    else:
        path = Path(source)
        if not path.is_file():
            raise UsageError(f"job description file not found: {path}")
        text, stem = path.read_text(encoding="utf-8"), path.stem
    if not text.strip():
        raise UsageError("the job description is empty")
    return text, stem


def _write_outputs(pdf_path: Path, doc: ResumeDoc, pdf: bytes | None) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    # The document is saved beside the PDF so it can be edited and rebuilt.
    pdf_path.with_suffix(".json").write_text(doc.model_dump_json(indent=2), encoding="utf-8")
    if pdf is not None:
        pdf_path.write_bytes(pdf)


def _report(pdf_path: Path, pdf: bytes | None, review: Review, summary: str) -> int:
    where = pdf_path if pdf is not None else pdf_path.with_suffix(".json")
    if review.passed:
        print(f"PASS  {where}  ({summary})")
    else:
        print(f"FAIL  {where}  ({summary}); still failing:")
        for failure in review.failures:
            print(f"  - {failure}")
        if pdf is None:
            print("  (no PDF: the document could not be rendered)")
    if review.shortfalls:
        print("Room to improve:")
        for shortfall in review.shortfalls:
            print(f"  - {shortfall}")
    if review.flags:
        print("Flags for review:")
        for flag in review.flags:
            print(f"  - {flag}")
    return EXIT_PASSED if review.passed else EXIT_FAILURES


def cmd_tailor(args: argparse.Namespace) -> int:
    job, stem = _read_job(args.job)
    master_path = data_dir() / MASTER_FILENAME
    master = load_master(master_path)
    # Fail before spending anything: a missing compiler found after the model
    # call would waste the call.
    find_tectonic()
    if args.backend == "claude-code":
        find_claude()
    result = tailor(
        master,
        master_path.read_text(encoding="utf-8"),
        job,
        write=BACKENDS[args.backend],
        judge=JUDGES[args.backend],
    )
    pdf_path = args.output or OUT_DIR / f"{stem}.pdf"
    _write_outputs(pdf_path, result.doc, result.pdf)
    attempts = len(result.attempts)
    summary = (
        f"{attempts} attempt{'s' if attempts > 1 else ''}, ${result.cost_usd:.2f} at list price"
    )
    checks = Review(result.failures, result.flags, result.shortfalls)
    code = _report(pdf_path, result.pdf, checks, summary)
    _report_judge(result)
    return code


def _report_judge(result: Tailored) -> None:
    """The judge's advice, after the checks: it never changes the exit code."""
    if result.verdict:
        print(f"Judge (advice only): {result.verdict.score}/100. {result.verdict.summary}")
        for gap in result.verdict.top_gaps():
            print(f"  - {gap}")
    elif result.judge_note:
        print(f"Judge: {result.judge_note}")


def cmd_build(args: argparse.Namespace) -> int:
    source = Path(args.document)
    if not source.is_file():
        raise UsageError(f"resume document not found: {source}")
    try:
        doc = ResumeDoc.model_validate_json(source.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise UsageError(f"{source} is not a valid resume document:\n{exc}") from None
    review, compiled = check(doc, load_master())
    pdf_path = args.output or source.with_suffix(".pdf")
    pdf = compiled.pdf if compiled else None
    if pdf is not None:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(pdf)
    return _report(pdf_path, pdf, review, "rebuilt, no model call")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="resume-maxer", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tailor", help="tailor a resume to a job description")
    t.add_argument("job", help="job description text file, or - for stdin")
    t.add_argument("-o", "--output", type=Path, help="PDF path (default: out/<job name>.pdf)")
    t.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default=BACKEND,
        help=f"how to reach Claude (default: {BACKEND})",
    )
    t.set_defaults(run=cmd_tailor)

    b = sub.add_parser("build", help="recompile and recheck an edited resume document")
    b.add_argument("document", help="resume document JSON, e.g. out/<job name>.json")
    b.add_argument("-o", "--output", type=Path, help="PDF path (default: beside the JSON)")
    b.set_defaults(run=cmd_build)

    s = sub.add_parser("serve", help="run the web app (behind a reverse proxy in production)")
    s.add_argument("--host", default="127.0.0.1", help="address to listen on (default: localhost)")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(run=cmd_serve)

    h = sub.add_parser("hash-password", help="print the web app's password hash and secret")
    h.set_defaults(run=cmd_hash_password)
    return parser


MIN_PASSWORD_CHARS = 12


def cmd_hash_password(args: argparse.Namespace) -> int:
    password = getpass.getpass("New web password: ")
    if len(password) < MIN_PASSWORD_CHARS:
        raise UsageError(f"use at least {MIN_PASSWORD_CHARS} characters")
    if getpass.getpass("Again: ") != password:
        raise UsageError("the passwords do not match")
    print("# Paste into the server's environment file (keep it private):")
    print(f"{PASSWORD_HASH_ENV}={hash_password(password)}")
    print(f"{SECRET_ENV}={secrets.token_urlsafe(48)}")
    return EXIT_PASSED


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    config = WebConfig.from_env()
    backend = os.environ.get(BACKEND_ENV, BACKEND)
    if backend not in BACKENDS:
        raise UsageError(f"{BACKEND_ENV} must be one of {', '.join(sorted(BACKENDS))}")
    # Check everything a run needs now, not on the first run from a phone.
    load_master()
    find_tectonic()
    if backend == "claude-code":
        find_claude()
    app = create_app(config, tailor_with(backend))
    # Trust X-Forwarded-For only from the local reverse proxy, so the login
    # limiter sees each visitor's real address.
    uvicorn.run(
        app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1"
    )
    return EXIT_PASSED


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (
        UsageError,
        MasterDataError,
        ClaudeError,
        TailorError,
        CompileError,
        ConfigError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
