"""Master resume data: the fact bank every generated bullet must trace back to."""

from collections import Counter
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal[
    "CURRENT",
    "ARCHIVED",
    "DEFENSIBLE ESTIMATE",
    "QUALITATIVE ONLY",
    "UNVERIFIED",
    "UNKNOWN",
    "INVALID",
]

# Policy, kept apart from the status labels themselves so it can be retuned in
# one place. UNVERIFIED waits for the owner's confirmation; INVALID and UNKNOWN
# are never usable. ARCHIVED stays selectable: whether the role justifies it is
# a judgement for the writer, not a hard rule.
SELECTABLE: frozenset[str] = frozenset(
    {"CURRENT", "ARCHIVED", "DEFENSIBLE ESTIMATE", "QUALITATIVE ONLY"}
)


class StrictModel(BaseModel):
    # A misspelled key ("metrcis") fails loudly instead of being silently dropped.
    model_config = ConfigDict(extra="forbid")


class Labeled(StrictModel):
    """A single value with its own confidence, e.g. a title that is UNVERIFIED."""

    value: str
    status: Status = "CURRENT"


class Link(StrictModel):
    label: str
    url: str
    status: Status = "CURRENT"


class Contact(StrictModel):
    name: str
    email: str | None = None
    links: list[Link] = []
    extras: list[str] = []


class Education(StrictModel):
    id: str
    school: str
    location: str
    degree: str
    dates: str
    gpa: Labeled | None = None
    honors: list[str] = []
    coursework: list[str] = []


class Credential(StrictModel):
    id: str
    text: str
    status: Status


class Variant(StrictModel):
    text: str
    # Bullet IDs this wording overlaps with and must not appear alongside.
    conflicts_with: list[str] = []


class Bullet(StrictModel):
    id: str
    status: Status
    tags: list[str] = []
    variants: dict[str, Variant] = Field(min_length=1)
    metrics: list[str] = []
    notes: list[str] = []


class Entry(StrictModel):
    id: str
    kind: Literal["experience", "leadership", "project"]
    name: str
    status: Status = "CURRENT"
    title: Labeled | None = None
    location: Labeled | None = None
    dates: Labeled
    stack: list[str] = []
    bullets: list[Bullet] = []
    notes: list[str] = []


class Metric(StrictModel):
    text: str
    status: Status
    notes: list[str] = []


class Skill(StrictModel):
    name: str
    category: str
    status: Status
    aliases: list[str] = []
    # Bullet or entry IDs that prove the skill. Empty means skills-section only.
    evidence: list[str] = []


class Master(StrictModel):
    contact: Contact
    education: list[Education]
    credentials: list[Credential] = []
    entries: list[Entry]
    metrics: dict[str, Metric]
    skills: list[Skill] = []

    @model_validator(mode="after")
    def _check_references(self) -> "Master":
        # Collect every problem before failing, so one load reports them all.
        problems: list[str] = []

        ids = [e.id for e in self.education]
        ids += [c.id for c in self.credentials]
        ids += [e.id for e in self.entries]
        ids += [b.id for e in self.entries for b in e.bullets]
        problems += [f"ID {i!r} is used more than once" for i, n in Counter(ids).items() if n > 1]

        bullet_ids = {b.id for e in self.entries for b in e.bullets}
        evidence_ids = bullet_ids | {e.id for e in self.entries}

        for entry in self.entries:
            for bullet in entry.bullets:
                for metric_id in bullet.metrics:
                    if metric_id not in self.metrics:
                        problems.append(
                            f"bullet {bullet.id!r} references unknown metric {metric_id!r}"
                        )
                for name, variant in bullet.variants.items():
                    for other in variant.conflicts_with:
                        if other not in bullet_ids:
                            problems.append(
                                f"bullet {bullet.id!r} variant {name!r} conflicts with "
                                f"unknown bullet {other!r}"
                            )

        for skill in self.skills:
            for ref in skill.evidence:
                if ref not in evidence_ids:
                    problems.append(f"skill {skill.name!r} cites unknown evidence {ref!r}")

        if problems:
            raise ValueError("\n".join(problems))
        return self

    def selectable_bullets(self) -> Iterator[tuple[Entry, Bullet]]:
        """Bullets the writer may use: both the bullet and its entry are SELECTABLE."""
        for entry in self.entries:
            if entry.status not in SELECTABLE:
                continue
            for bullet in entry.bullets:
                if bullet.status in SELECTABLE:
                    yield entry, bullet

    def tech_names(self) -> list[str]:
        """Names containing digits (ROS 2, Sonnet 4.6) that the number check must skip."""
        names = {n for s in self.skills for n in (s.name, *s.aliases)}
        for entry in self.entries:
            names.update(entry.stack)
            names.update(t for b in entry.bullets for t in b.tags)
        return sorted(n for n in names if any(c.isdigit() for c in n))
