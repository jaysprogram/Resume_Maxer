"""A resume document: the choices for one page, as the writer (or a person) makes them.

It names entries by ID only. Names, titles, locations and dates always come from
the master data, so whoever writes the document cannot change a job title.
"""

from pydantic import Field

from resume_maxer.schema import SELECTABLE, Master, StrictModel

# Which entry kinds each section may hold. Leadership sits under Experience,
# as on the preferred resume.
SECTION_KINDS = {"experience": {"experience", "leadership"}, "projects": {"project"}}


class DocBullet(StrictModel):
    source_ids: list[str] = Field(min_length=1)
    text: str
    bold: list[str] = []  # phrases of `text` to set in bold, 1-2 per bullet


class DocEntry(StrictModel):
    entry_id: str
    # Projects only: the subset of the master stack to show in the heading.
    stack: list[str] = []
    bullets: list[DocBullet] = []


class SkillLine(StrictModel):
    label: str
    items: list[str] = Field(min_length=1)


class ResumeDoc(StrictModel):
    credentials: list[str] = []  # credential IDs shown under Education
    skills: list[SkillLine] = []
    experience: list[DocEntry] = []
    projects: list[DocEntry] = []


def problems(doc: ResumeDoc, master: Master) -> list[str]:
    """Everything in `doc` that its master data does not back. Empty means usable.

    Structural only: number provenance and wording rules are checked elsewhere.
    """
    entries = {e.id: e for e in master.entries}
    credentials = {c.id: c for c in master.credentials}
    found = []

    for cred_id in doc.credentials:
        cred = credentials.get(cred_id)
        if cred is None:
            found.append(f"unknown credential {cred_id!r}")
        elif cred.status not in SELECTABLE:
            found.append(f"credential {cred_id!r} is {cred.status}")
        elif cred.text in master.contact.extras:
            found.append(f"credential {cred_id!r} repeats the header's {cred.text!r}")

    for section, kinds in SECTION_KINDS.items():
        for doc_entry in getattr(doc, section):
            entry = entries.get(doc_entry.entry_id)
            if entry is None:
                found.append(f"unknown entry {doc_entry.entry_id!r}")
                continue
            if entry.status not in SELECTABLE:
                found.append(f"entry {entry.id!r} is {entry.status}")
            if entry.kind not in kinds:
                found.append(f"entry {entry.id!r} is a {entry.kind}, not allowed in {section}")
            for item in doc_entry.stack:
                if item not in entry.stack:
                    found.append(
                        f"entry {entry.id!r} stack item {item!r} is not in its master stack"
                    )

            own = {b.id: b for b in entry.bullets}
            for bullet in doc_entry.bullets:
                for source in bullet.source_ids:
                    if source not in own:
                        found.append(
                            f"entry {entry.id!r} bullet cites {source!r}, not one of its own"
                        )
                    elif (status := own[source].status) not in SELECTABLE:
                        found.append(
                            f"entry {entry.id!r} bullet cites {source!r}, which is {status}"
                        )
    return found
