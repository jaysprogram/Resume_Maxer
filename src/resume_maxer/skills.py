"""Which parts of a skills-line item the master data does not back.

Measurement only; review.py decides that any unbacked part is a failure.

An item may group related skills, as in "AWS (EC2, Lambda)" or "C# / .NET",
so it is split into parts and each part is looked up. A part inside a group
also counts when its head plus the part is a known name: "Lambda" under "AWS"
matches "AWS Lambda". Matching ignores case and spacing, nothing else, so a
typo ("NET" for ".NET") or an invented skill ("Power BI") is caught.
"""

import re
from dataclasses import dataclass

from resume_maxer.schema import SELECTABLE, Master

_GROUP = re.compile(r"^(?P<head>[^()]*?)\s*\((?P<inner>[^()]*)\)$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _split_top(text: str, sep: str) -> list[str]:
    """Split on `sep` outside parentheses: "C# / .NET (ASP.NET)" -> ["C# ", " .NET (ASP.NET)"]."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    return [*parts, text[start:]]


@dataclass(frozen=True)
class Vocabulary:
    usable: frozenset[str]  # normalized names a skills line may show
    blocked: dict[str, str]  # normalized name -> status, for skills that may not be shown


def vocabulary(master: Master) -> Vocabulary:
    usable, blocked = set(), {}
    for skill in master.skills:
        names = [skill.name, *skill.aliases]
        # "Claude / LLM APIs" may be shown whole or as either side.
        names += [p for n in names if "/" in n for p in _split_top(n, "/")]
        for name in map(_norm, names):
            if skill.status in SELECTABLE:
                usable.add(name)
            else:
                blocked.setdefault(name, skill.status)
    for entry in master.entries:
        if entry.status is None or entry.status in SELECTABLE:
            usable.update(map(_norm, entry.stack))
    return Vocabulary(frozenset(usable), {k: v for k, v in blocked.items() if k not in usable})


def unbacked_parts(item: str, vocab: Vocabulary) -> list[str]:
    """The parts of `item` the master does not back, with why. Empty means backed."""
    found = []
    # The template joins items with ", ", so a comma outside parentheses separates
    # items on the page too: "Python, Go" is checked as two items.
    for single in _split_top(item, ","):
        if single.strip() and _norm(single) not in vocab.usable:
            found += _unbacked_in_one(single, vocab)
    return found


def _unbacked_in_one(item: str, vocab: Vocabulary) -> list[str]:
    found = []
    pieces = _split_top(item, "/")
    for piece in pieces if len(pieces) > 1 else [item]:
        group = _GROUP.match(piece.strip())
        head = group["head"] if group else piece
        inner = [p for p in group["inner"].split(",") if p.strip()] if group else []
        candidates = [(head, [head])] + [(p, [p, f"{head} {p}"]) for p in inner]
        for shown, names in candidates:
            if not shown.strip():
                continue
            if any(_norm(n) in vocab.usable for n in names):
                continue
            status = next(
                (vocab.blocked[_norm(n)] for n in names if _norm(n) in vocab.blocked), None
            )
            why = f"is {status} in the master" if status else "is not a skill in the master"
            found.append(f"{shown.strip()!r} {why}")
    return found
