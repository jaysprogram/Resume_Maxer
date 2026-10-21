# CLAUDE.md — Resume Maxer

Project-specific guidance. The shared `dev/CLAUDE.md` still applies; where they
conflict, this file wins, and say so.

## Commands

Run from PowerShell (Windows) or any shell with uv:

- `uv sync` — install dependencies into `.venv`
- `uv run pytest` — run tests
- `uv run ruff check .` and `uv run ruff format --check .` — lint and format
- `uv run resume-maxer tailor JOB.txt` — tailor a resume (calls Claude; costs usage)
- `uv run resume-maxer build out/JOB.json` — recheck + recompile an edited document (free)

Tectonic 0.17.0 is installed on Windows at `%LOCALAPPDATA%\Programs\tectonic\tectonic.exe`
(and in WSL at `~/.local/bin/tectonic`). Compile tests need it on `PATH` or the
`TECTONIC` environment variable set; otherwise they skip locally.

## Design rules (agreed; see README "Why it is built this way")

- The LLM returns structured data. It never writes LaTeX.
- Every string reaching the template goes through `resume_maxer.latex.latex_escape`.
  It is the only escaping function; do not add a second one.
- Number provenance and line width are enforced by code/LaTeX, not by a model.
- Compiler: Tectonic with fontspec + OpenType XCharter. Do not reintroduce
  `\input{glyphtounicode}` / `\pdfgentounicode` (pdfTeX-only).

## Personal data

The repo is public. Resume sources, `HANDOFF.md`, the `*Resume_Context_Package/`
folder, `data/`, `out/`, `*.pdf`, `*.local.json` and `.env` are gitignored. Never commit
them, and never copy real names, contact details, employers or metrics into tests,
fixtures or examples; use fictional data.

## Security checklist (run on every diff)

- Job-description and model text is untrusted: escape it before rendering and
  validate model output against a schema.
- Never enable shell-escape when compiling; compile in a temp dir with a timeout.
- Spawn processes with an argument list, never an interpolated shell string.
- No API keys, tokens or personal paths in committed files.

## Learning mode

The owner uses this project to learn. Major design decisions are theirs: ask
for their approach before proposing one. Notes live in `.vibe-wise/` (gitignored).
