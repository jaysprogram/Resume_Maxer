# Resume Maxer

Tailors a resume to a job description and compiles a one-page LaTeX PDF that
parses cleanly in applicant tracking systems (ATS).

> Status: working end to end: command line and a password-protected web app.

## Usage

Put your master data in `data/master.json` (see [Master data](#master-data)),
save a job description as a text file, then:

```sh
uv run resume-maxer tailor job.txt           # PDF + resume document in out/
uv run resume-maxer tailor - < job.txt       # or read the posting from stdin
uv run resume-maxer build out/job.json       # recheck + recompile after editing the JSON
```

`tailor` prints `PASS` or `FAIL` with anything that still fails, plus flags
for review. It always writes the resume document (`out/job.json`) beside the
PDF: edit a wording there and run `build` to recompile and recheck it with no
model call. Exit codes: `0` passed, `1` a PDF was written but checks still
fail, `2` an error (the message says what to fix).

The default backend is Claude Code on a logged-in subscription; pass
`--backend api` to use an API key instead (`uv run --env-file .env ...`).

## Web app

Paste a posting from a phone, get the PDF. `resume-maxer serve` runs it on
`127.0.0.1:8000`; in production it sits behind a reverse proxy that adds HTTPS.

```sh
uv run resume-maxer hash-password   # prints the two settings below; paste them into the env file
uv run --env-file .env resume-maxer serve
```

| Setting | Meaning |
|---|---|
| `RESUME_WEB_PASSWORD_HASH` | scrypt hash of the one password (never the password itself) |
| `RESUME_WEB_SECRET` | 32+ random characters that sign the session cookie |
| `RESUME_BACKEND` | `claude-code` (subscription) or `api` (API key); default `claude-code` |
| `RESUME_RUNS_DIR` | where runs are kept; default `out/web` (gitignored) |
| `RESUME_WEB_INSECURE_COOKIES` | `1` only to test over plain http on your own machine |

- **Runs** take one to three minutes, so they are queued and worked one at a
  time in the background. A run's page refreshes itself until the PDF is ready
  (no JavaScript); runs survive restarts, and one cut off by a restart is
  marked interrupted.
- **Security:** one password, stored only as a scrypt hash; a signed session
  cookie that is `HttpOnly`, `Secure` and `SameSite=Strict` (which also stops
  other sites posting forms here); 5 failed logins per address per 15 minutes,
  counted per visitor's real address via the proxy's `X-Forwarded-For` (trusted
  only from localhost); no API docs; a strict Content-Security-Policy; pages
  marked `no-store`; postings capped at 50,000 characters and oversized
  requests refused before parsing; run IDs must be 32 hex characters, so a
  crafted URL cannot reach other files.
- `serve` checks the settings, the master data and the tools at startup, so a
  misconfigured server fails at once rather than on the first run.

### Deploy (Ubuntu, Caddy, systemd)

`deploy/` holds everything for a server that already runs Caddy with
`import /etc/caddy/sites/*.caddy`:

1. Point a DNS A record (`resume.example.com`) at the server, and set that
   name in `deploy/resume.caddy`.
2. As root: `git clone` this repo to `/opt/resume-maxer`, then
   `bash /opt/resume-maxer/deploy/setup.sh`. It creates the `resume-maxer`
   system user, installs the pinned Tectonic (checksum-verified, the version CI
   uses, from `deploy/tectonic.env`), builds the venv with the system Python,
   warms Tectonic's font cache, installs the hardened systemd unit, and adds
   the Caddy site (validating the whole Caddy config before reloading).
3. Copy your master data to `/var/lib/resume-maxer/data/master.json`
   (owner `resume-maxer`, mode `600`).
4. Interactively on the server: `bash /opt/resume-maxer/deploy/set-secrets.sh`
   (nothing is echoed or put on a command line), then run `setup.sh` again to
   start the service. It asks for the web password and how to reach Claude:
   - an **Anthropic API key**: the `api` backend, billed per run (about $0.14
     to $0.28 a resume); or
   - a **Claude subscription token**: run `claude setup-token` on a machine
     where you are logged in to Claude Code and paste the token. This is the
     `claude-code` backend; `setup.sh` installs the app's own pinned Claude
     Code in `/opt/resume-maxer-claude` (outside `/root`, apart from any other
     Claude Code on the server), and runs count against the subscription's
     usage limits.

Updates: push to GitHub, then rerun `setup.sh`.

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
- **What is only flagged:** a unit after the number that the metrics never use
  (`~20K dollars`). Rewording "attendees" as "students" is the writer's job, so
  this is shown for review rather than blocking. The unit is the run of lowercase
  words after the number: names and acronyms in between are skipped (`~20 Example Club
  attendees`), a joining word ends it (`500+ GitHub repos through`), and it
  matches if any of its words is a metric's unit, so describing words are fine
  (`~6 overnight survey flights`). Abbreviations and plurals are the same
  unit (`5+ min` for `5+ minutes`). Before this rule, three false flags showed
  on nearly every real resume; after it, none across 12.
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

The writer asks Claude for a resume document in one call, using structured
outputs so the answer is validated straight into `ResumeDoc`. How the question
reaches Claude lives in `claude.py`, shared with the judge.

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

## Check and repair

`pipeline.tailor` runs the whole loop: the writer drafts a document, then code
checks it (`review.review`): structure, skills, number provenance, page
count, every line's width, and missing glyphs.

- **Skills** (`skills.py`): every item on a skills line must be a usable master
  skill name or alias, or a usable entry's stack item, ignoring case and
  spacing. Groups are checked part by part: in `AWS (EC2, Lambda)`, "Lambda"
  counts if "Lambda" or "AWS Lambda" is known. A typo (`NET` for `.NET`), an
  invented skill, or an `UNVERIFIED` one fails.

- Each **failure** says what is wrong and what to do, precisely enough for a
  model to act on: `ACME.1 uses 133% of the line (at most 99% fits): cut at
  least 48 characters from '...'`.
- Any failure gets **one repair**: the writer receives the failed document
  and its failures, and is asked to fix only those. The instructions and
  master stay the same, so the cached prefix is reused; a measured repair cost
  about $0.05 and changed only the two failing bullets out of 18.
- An **under-filled page** is a *shortfall*: 3 or more bullet lines of empty
  space below the text (`checks.UNDERFILL_LINES`; the preferred resume leaves
  about 1.6). The template logs how far down the page the text reaches after
  every line (`PAGEFILL`). A shortfall triggers the repair ("add a relevant
  bullet") but never fails the resume, and counts less than any failure.
- If the repair also fails, the **better attempt** is returned (a rendered
  document over an unrendered one, then fewer failures, then fewer shortfalls,
  so an under-filled one-page draft beats a repair that spilled onto two pages;
  a tie goes to the repair) with the list of what still fails. Nothing is hidden.
- **Flags** are shown for review and never trigger a repair: a changed unit
  after a number, and **borrowed terms** (`terms.py`): a bullet word that comes
  from the posting but appears nowhere in that bullet's own facts (its master
  wordings, tags, notes, metrics, entry stack, and the aliases of skills those
  facts name). The writer may use the posting's vocabulary where the facts
  support it; this lists every such word so a person can confirm it is true.

## The judge (advice only)

After the loop, `judge.py` asks Claude Haiku 5.5 to score the final page
against the posting, from 0 to 100 on a fixed rubric, with up to five gaps. It
reads the text an ATS extracts from the PDF. It costs about $0.001.

The score is reported, never used as a gate. A calibration run scored 11
resume and posting pairs twice each: a resume tailored for the posting scored
about the same as an untailored one (on one posting, a resume tailored for a
*different* job scored highest), and the same page moved up to 11 points
between runs. What the score tracks is the candidate's fit for the posting,
which rewording cannot change. The gaps are useful as advice: some point to
buried evidence, others to experience the master does not have, which only
real work, recorded in the master, can address.

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
