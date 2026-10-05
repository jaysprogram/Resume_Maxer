# Resume Maxer

Tailors a resume to a job description and compiles a one-page LaTeX PDF that
parses cleanly in applicant tracking systems (ATS).

> Status: early. The pipeline below is the agreed design; only LaTeX escaping
> is implemented so far.

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
