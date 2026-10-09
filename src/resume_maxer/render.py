"""Render a ResumeDoc to LaTeX: check it against the master, then fill the template."""

import re
from pathlib import Path

import jinja2

from resume_maxer.latex import latex_escape
from resume_maxer.resume_doc import ResumeDoc, problems
from resume_maxer.schema import SELECTABLE, Entry, Master

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_NAME = "resume.tex.j2"

# hyperref reads \href's URL almost verbatim, so latex_escape cannot make an
# arbitrary URL safe. Contact URLs never need more than these characters.
_SAFE_URL = re.compile(r"^(https?://|mailto:)[A-Za-z0-9._/@:-]+$")


class RenderError(ValueError):
    """The document cannot be rendered against this master data."""


def url(value: str) -> str:
    if not _SAFE_URL.match(value):
        raise RenderError(f"unsupported characters in URL {value!r}")
    return value


def bolded(text: str, phrases: list[str]) -> str:
    """Escape `text` and set each phrase in bold. Nobody writes \\textbf by hand."""
    spans = []
    for phrase in phrases:
        start = text.find(phrase) if phrase else -1
        if start < 0:
            raise RenderError(f"bold phrase {phrase!r} is not in {text!r}")
        spans.append((start, start + len(phrase)))
    spans.sort()
    if any(nxt[0] < cur[1] for cur, nxt in zip(spans, spans[1:], strict=False)):
        raise RenderError(f"bold phrases overlap in {text!r}")

    parts, pos = [], 0
    for start, end in spans:
        parts.append(latex_escape(text[pos:start]))
        parts.append(r"\textbf{" + latex_escape(text[start:end]) + "}")
        pos = end
    parts.append(latex_escape(text[pos:]))
    return "".join(parts)


def _environment() -> jinja2.Environment:
    # LaTeX owns { } % and #, so Jinja's markers are moved out of their way.
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # escaping is explicit, through the filters below
        undefined=jinja2.StrictUndefined,  # a typo in the template fails loudly
    )
    env.filters.update(latex=latex_escape, bolded=bolded, url=url)
    return env


def _entry_view(entry: Entry, stack: list[str], bullets) -> dict:
    return {
        "name": entry.name,
        "title": entry.title.value if entry.title else "",
        "location": entry.location.value if entry.location else "",
        "dates": entry.dates.value,
        "stack": stack,
        # The key labels each bullet's width in the compile log.
        "bullets": [
            {"key": f"{entry.id}.{i}", "text": b.text, "bold": b.bold}
            for i, b in enumerate(bullets, start=1)
        ],
    }


def render(doc: ResumeDoc, master: Master) -> str:
    found = problems(doc, master)
    if found:
        raise RenderError("\n".join(found))

    entries = {e.id: e for e in master.entries}
    credentials = {c.id: c.text for c in master.credentials}
    contact = master.contact

    header = [{"label": contact.email, "url": f"mailto:{contact.email}"}] if contact.email else []
    header += [
        {"label": link.label, "url": link.url}
        for link in contact.links
        if link.status in SELECTABLE
    ]
    header += [{"label": extra, "url": ""} for extra in contact.extras]

    education = [
        {
            "school": edu.school,
            "location": edu.location,
            "degree": edu.degree,
            "dates": edu.dates,
            "gpa": edu.gpa.value if edu.gpa and edu.gpa.status in SELECTABLE else "",
            "honors": edu.honors,
            "coursework": edu.coursework,
        }
        for edu in master.education
    ]

    def section(doc_entries):
        return [_entry_view(entries[d.entry_id], d.stack, d.bullets) for d in doc_entries]

    return (
        _environment()
        .get_template(TEMPLATE_NAME)
        .render(
            contact=contact,
            header=header,
            education=education,
            credentials=[credentials[c] for c in doc.credentials],
            skills=doc.skills,
            experience=section(doc.experience),
            projects=section(doc.projects),
        )
    )
