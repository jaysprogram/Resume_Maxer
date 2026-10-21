"""The command line: files in, files out, exit codes and messages."""

import io
import json
import sys

import pytest
from anthropic.types import Usage

from resume_maxer import cli
from resume_maxer.pipeline import Attempt, Tailored, TailorError
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.writer import BACKENDS, WriterResult


@pytest.fixture
def workspace(tmp_path, monkeypatch, sample_data):
    """A working folder with the fictional master as the data folder."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "master.json").write_text(json.dumps(sample_data), encoding="utf-8")
    monkeypatch.setenv("RESUME_DATA_DIR", str(data))
    # tailor checks both tools exist before calling the model; any real file will do.
    monkeypatch.setenv("TECTONIC", sys.executable)
    monkeypatch.setenv("CLAUDE_CODE", sys.executable)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "acme_job.txt").write_text("We want Go and PostgreSQL.", encoding="utf-8")
    return tmp_path


def tailored(doc_data, failures=(), flags=(), costs=(0.15,), pdf=b"%PDF-fake"):
    attempts = [
        Attempt(
            WriterResult(
                doc=None,
                stop_reason="completed",
                usage=Usage(input_tokens=0, output_tokens=0),
                cost_usd=cost,
                request_id=None,
            ),
            None,
            None,
        )
        for cost in costs
    ]
    return Tailored(
        doc=ResumeDoc.model_validate(doc_data),
        pdf=pdf,
        failures=list(failures),
        flags=list(flags),
        attempts=attempts,
    )


@pytest.fixture
def fake_tailor(monkeypatch):
    calls = []

    def install(result=None, error=None):
        def fake(master, master_json, job, *, write):
            calls.append({"job": job, "write": write, "master": master})
            if error:
                raise error
            return result

        monkeypatch.setattr(cli, "tailor", fake)
        return calls

    return install


def test_tailor_writes_pdf_and_document_and_passes(workspace, fake_tailor, sample_doc_data, capsys):
    calls = fake_tailor(tailored(sample_doc_data, flags=["WTHR.1 '...': unit flag"]))
    assert cli.main(["tailor", "acme_job.txt"]) == cli.EXIT_PASSED

    assert (workspace / "out" / "acme_job.pdf").read_bytes() == b"%PDF-fake"
    saved = json.loads((workspace / "out" / "acme_job.json").read_text(encoding="utf-8"))
    assert ResumeDoc.model_validate(saved) == ResumeDoc.model_validate(sample_doc_data)
    out = capsys.readouterr().out
    assert "PASS" in out and "acme_job.pdf" in out and "1 attempt, $0.15" in out
    assert "Flags for review:\n  - WTHR.1" in out
    assert calls[0]["job"] == "We want Go and PostgreSQL."
    assert calls[0]["write"] is BACKENDS["claude-code"]  # the default backend


def test_tailor_with_remaining_failures_still_writes_the_pdf(
    workspace, fake_tailor, sample_doc_data, capsys
):
    fake_tailor(tailored(sample_doc_data, failures=["ACME.1 uses 104%"], costs=(0.15, 0.05)))
    assert cli.main(["tailor", "acme_job.txt", "-o", "x/r.pdf"]) == cli.EXIT_FAILURES
    assert (workspace / "x" / "r.pdf").exists() and (workspace / "x" / "r.json").exists()
    out = capsys.readouterr().out
    assert "FAIL" in out and "2 attempts, $0.20" in out and "  - ACME.1 uses 104%" in out


def test_tailor_reads_the_job_from_stdin(workspace, fake_tailor, sample_doc_data, monkeypatch):
    calls = fake_tailor(tailored(sample_doc_data))
    monkeypatch.setattr("sys.stdin", io.StringIO("Pasted from a phone."))
    assert cli.main(["tailor", "-"]) == cli.EXIT_PASSED
    assert calls[0]["job"] == "Pasted from a phone."
    assert (workspace / "out" / "resume.pdf").exists()


def test_backend_flag_selects_the_api(workspace, fake_tailor, sample_doc_data):
    calls = fake_tailor(tailored(sample_doc_data))
    cli.main(["tailor", "acme_job.txt", "--backend", "api"])
    assert calls[0]["write"] is BACKENDS["api"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["tailor", "missing.txt"], "job description file not found: missing.txt"),
        (["tailor", "empty.txt"], "the job description is empty"),
        (["build", "missing.json"], "resume document not found: missing.json"),
    ],
)
def test_bad_input_is_an_error_before_any_model_call(workspace, fake_tailor, capsys, args, message):
    (workspace / "empty.txt").write_text("  \n", encoding="utf-8")
    calls = fake_tailor()
    assert cli.main(args) == cli.EXIT_ERROR
    assert capsys.readouterr().err.strip() == f"error: {message}"
    assert calls == []


def test_writer_failure_reaches_the_user(workspace, fake_tailor, capsys):
    fake_tailor(error=TailorError("the writer produced no resume document (refused)"))
    assert cli.main(["tailor", "acme_job.txt"]) == cli.EXIT_ERROR
    assert "error: the writer produced no resume document (refused)" in capsys.readouterr().err
    assert not (workspace / "out").exists()


def test_missing_master_says_where_it_looked(workspace, fake_tailor, capsys, monkeypatch):
    monkeypatch.setenv("RESUME_DATA_DIR", str(workspace / "nowhere"))
    fake_tailor()
    assert cli.main(["tailor", "acme_job.txt"]) == cli.EXIT_ERROR
    assert "RESUME_DATA_DIR" in capsys.readouterr().err


def test_build_rejects_a_document_that_is_not_one(workspace, capsys):
    (workspace / "bad.json").write_text('{"skills": "everything"}', encoding="utf-8")
    assert cli.main(["build", "bad.json"]) == cli.EXIT_ERROR
    assert "bad.json is not a valid resume document" in capsys.readouterr().err


# --- build compiles for real ---------------------------------------------------


def test_build_recompiles_an_edited_document(
    workspace, tectonic, sample_doc_data, capsys, monkeypatch
):
    monkeypatch.setenv("TECTONIC", tectonic)  # the real one, not the workspace stand-in
    (workspace / "r.json").write_text(json.dumps(sample_doc_data), encoding="utf-8")
    assert cli.main(["build", "r.json"]) == cli.EXIT_PASSED
    assert (workspace / "r.pdf").read_bytes().startswith(b"%PDF")
    assert "PASS" in capsys.readouterr().out


def test_build_reports_what_an_edit_broke(
    workspace, tectonic, sample_doc_data, capsys, monkeypatch
):
    monkeypatch.setenv("TECTONIC", tectonic)
    sample_doc_data["experience"][0]["bullets"][0]["text"] = "Shipped it to 40 field testers"
    sample_doc_data["experience"][0]["bullets"][0]["bold"] = []
    (workspace / "r.json").write_text(json.dumps(sample_doc_data), encoding="utf-8")
    assert cli.main(["build", "r.json"]) == cli.EXIT_FAILURES
    out = capsys.readouterr().out
    assert "FAIL" in out and "'~40'" in out
    assert (workspace / "r.pdf").exists()  # still written, so the person can look


@pytest.mark.parametrize(
    ("variable", "backend", "tool"),
    [("TECTONIC", "claude-code", "TECTONIC"), ("CLAUDE_CODE", "claude-code", "CLAUDE_CODE")],
)
def test_missing_tool_stops_before_any_model_call(
    workspace, fake_tailor, capsys, monkeypatch, variable, backend, tool
):
    # Regression: a compiler found missing only after the model call wasted the call.
    monkeypatch.setenv(variable, str(workspace / "nope.exe"))
    calls = fake_tailor()
    assert cli.main(["tailor", "acme_job.txt", "--backend", backend]) == cli.EXIT_ERROR
    assert calls == []
    assert f"{tool} is set to" in capsys.readouterr().err


def test_api_backend_does_not_need_claude_code(
    workspace, fake_tailor, sample_doc_data, monkeypatch
):
    monkeypatch.setenv("CLAUDE_CODE", str(workspace / "nope.exe"))
    calls = fake_tailor(tailored(sample_doc_data))
    assert cli.main(["tailor", "acme_job.txt", "--backend", "api"]) == cli.EXIT_PASSED
    assert len(calls) == 1
