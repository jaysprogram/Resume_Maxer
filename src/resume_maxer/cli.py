"""Command line: tailor a resume to a job description, or rebuild an edited one.

  resume-maxer tailor JOB.txt          write, check, repair once; PDF + JSON in out/
  resume-maxer tailor -                read the job description from stdin
  resume-maxer build out/JOB.json      recompile and recheck a hand-edited document

Exit codes: 0 every check passed, 1 a PDF was written but checks still fail,
2 nothing usable was produced (the message says why).
"""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from resume_maxer.compile import CompileError, find_tectonic
from resume_maxer.load import MASTER_FILENAME, MasterDataError, data_dir, load_master
from resume_maxer.pipeline import TailorError, check, tailor
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.review import Review
from resume_maxer.writer import BACKEND, BACKENDS, WriterError, find_claude

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
    )
    pdf_path = args.output or OUT_DIR / f"{stem}.pdf"
    _write_outputs(pdf_path, result.doc, result.pdf)
    attempts = len(result.attempts)
    summary = (
        f"{attempts} attempt{'s' if attempts > 1 else ''}, ${result.cost_usd:.2f} at list price"
    )
    return _report(pdf_path, result.pdf, Review(result.failures, result.flags), summary)


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (UsageError, MasterDataError, WriterError, TailorError, CompileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
