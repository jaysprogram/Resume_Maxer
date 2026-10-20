# Resume Maxer

Tailors a resume to a job description and compiles a one-page LaTeX PDF that
parses cleanly in applicant tracking systems (ATS).

> Status: early. The pipeline below is the agreed design. Implemented so far:
> LaTeX escaping, the master-data schema/loader, the number check, rendering +
> compiling a resume document to a measured one-page PDF, and the writer call.
> The retry loop and a command-line entry point are next.

## How it works (design)

```
job description
  -> LLM extracts ATS keywords
  -> keywords compared with the master fact bank (alias-aware)
  -> LLM writes bullets as structured data, each tagged with its source fact IDs
  -> code checks every number in a bullet appears in its tagged facts
  -> a second model scores the resume against the job description
  -> template renders LaTeX -> Tectonic compiles -> LaTeX measures each bullet's width
  -> any failure: one retry with the specific failures
     -> still failing: best attempt plus a list of what still fails
```

## Why it is built this way

- **The model never writes LaTeX.** It returns structured data; code fills a
  template and escapes every string. Ten ordinary characters (`& % $ # _ { } ~ ^ \`)
  are LaTeX commands, and a model that forgets to escape one either breaks the
  compile or silently drops text (`50% in Q3` prints as `50`).
- **Hard rules are checked in code, not by a model.** "Is every number true?"
  and "does this bullet fit on one line?" have exact answers. Code and LaTeX
  give the same answer every run; a model judge does not.
- **Numbers are checked against the bullet's own sources,** not the whole fact
  bank, so a figure borrowed from a different job is caught.
- **Line width is measured by LaTeX after typesetting.** Character counts cannot
  know rendered width in a proportional font with bold spans.
- **Tectonic + OpenType XCharter.** A single binary keeps the server small. The
  8-bit `charter` font under XeTeX extracts "fi"/"fl" as ligature glyphs (`ﬁles`),
  which ATS keyword search can miss; the OpenType font extracts plain letters,
  identical to pdfLaTeX.

## Master data

All facts live in one JSON file, `master.json`, read from the folder named by
`RESUME_DATA_DIR` (default `data/`, which is gitignored). The format is shown by
the fictional [`examples/sample_master.json`](examples/sample_master.json).

- **Entries** (experience, leadership, projects) hold **bullets**. Each bullet
  has one or more wording `variants`, `tags`, `notes`, and the IDs of the
  **metrics** it may use.
- **Metrics** live in one top-level table keyed by ID. A number may appear in a
  generated bullet only if it comes from one of that bullet's metrics.
- **Skills** list aliases (for job-description matching) and evidence (bullet or
  entry IDs). A skill with no evidence belongs in the skills section only.
- Every fact carries a status: `CURRENT`, `ARCHIVED`, `DEFENSIBLE ESTIMATE`,
  `QUALITATIVE ONLY`, `UNVERIFIED`, `UNKNOWN` or `INVALID`. Only the first four
  are ever offered to the writer; the rest stay in the file as a record of what
  not to claim.

Loading fails with a message naming the problem when a referenced ID does not
exist, an ID is used twice, a status or field name is misspelled, or the JSON
repeats a key.

## The number check

Every number in a generated bullet must appear in the metrics that bullet cites.

- **What counts as a number:** digits, plus spelled-out *two* to *ten*. Names
  that contain digits are skipped when digits are glued to letters (`YOLOv8`,
  `Nav2`) or the name appears in the master data's skills, aliases, stacks or
  tags (`ROS 2`, `Sonnet 4.6`). A digit-bearing name missing from the data is
  treated as a number, the safe direction. *One* is not counted: it is common
  in plain English ("one-time") and never carried a metric in testing.
- **What must match (fails the bullet):** the value, the estimate markers `~`
  and `+`, and the symbols `$`, `%`, `K`. *approximately* and *about* count as
  `~`. So `1,000` fails against `~1,000`, and `$20K` fails against `~20K tokens`.
- **What is only flagged:** a unit word after the number that the metrics never
  use (`~20K dollars`). Rewording "attendees" as "students" is the writer's job,
  so this is shown for review rather than blocking.
- Known false alarm: "learned about 3 tools" reads *about* as an estimate marker.

## Rendering and compiling

The writer's decisions form a **resume document** (see
[`examples/sample_resume_doc.json`](examples/sample_resume_doc.json)): which
entries, which bullets with what wording, which phrases are bold, in what order.
It names entries by ID only, so names, titles and dates always come from the
master data. The template does not care whether a model or a person wrote it.

- `render` checks the document against the master (unknown or unusable
  entries, bullets citing another entry's facts, stack items not in the master,
  a credential the header already shows)
  and fills `src/resume_maxer/templates/resume.tex.j2`, a Jinja2 template using
  `\VAR{}` / `\BLOCK{}` markers so they do not collide with LaTeX. Every value
  passes through `latex_escape`; bold phrases are wrapped by code.
- `compile_tex` runs Tectonic with `--untrusted` in a throwaway folder with a
  timeout, and reads back what LaTeX measured: page count, the width of each
  bullet and each skills line against the line, and any character the font
  lacks (which would otherwise print as nothing).
- A bullet or skills line fits when it uses at most 99% of the line
  (`checks.FIT_RATIO`). Skills lines are measured too: one that wraps costs a
  whole line and can push the page to two.

Tectonic must be on `PATH`, or `TECTONIC` must point to the executable.
Compile tests skip locally without it and fail in CI, which installs a pinned,
checksum-verified release.

## The writer

`writer.write_resume` asks Claude for a resume document in one call, using
structured outputs so the answer is parsed straight into `ResumeDoc`.

- **Model:** Claude Sonnet 5.5 at `high` effort (`writer.MODEL`, `writer.EFFORT`).
  In a side-by-side run on one posting, Haiku 5.5 and Sonnet 5.5 at medium and
  high effort all passed every code check; Sonnet at high effort chose the
  entries that best matched the posting. Haiku was about 7x cheaper but chose
  weaker content.
- **Cost:** about $0.14 per resume with a cold cache, about $0.08 when the
  master data is still cached (within 5 minutes). The whole master goes in a
  cached system block; the job description goes in the user turn.
- **Trust:** the job description is treated as untrusted text, and the model's
  answer is never trusted either: it passes through the same checks as a
  hand-written document.
- **Two ways to reach Claude** (`writer.BACKENDS`, same instructions and checks):
  - `claude-code` (the default, `writer.BACKEND`): runs Claude Code headless
    (`claude -p`) on its logged-in Claude subscription. The model gets no tools,
    runs in an empty temp folder (so no `CLAUDE.md` or memory leaks into the
    prompt), and receives the job description on stdin. Claude Code must be on
    `PATH`, or `CLAUDE_CODE` must point to the executable. Its reported cost is
    the list-price equivalent; a subscription is not billed per token.
  - `api`: the Anthropic SDK with an API key (`ANTHROPIC_API_KEY` or another
    credential source the SDK supports). Keep keys in `.env`, which is
    gitignored. This is the path for a server without a subscription.

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
uv run ruff check .
```

Personal data (resume sources, generated PDFs, `.env`) is gitignored and never
committed.

## License

MIT. See [LICENSE](LICENSE).
