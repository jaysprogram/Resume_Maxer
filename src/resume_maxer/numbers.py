"""Number provenance: every number in a generated bullet must come from its metrics.

Measurement (extract_numbers: what numbers a text contains) is kept apart from
policy (check_numbers: which of them are allowed), so either can be retuned alone.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Words that mark an estimate as firmly as "~" does. Writing "approximately 10"
# for a "~10" metric keeps the estimate an estimate; writing "10" does not.
APPROX_WORDS = ("approximately", "about")

# "one" is left out on purpose: it is everywhere in plain English ("one-time",
# "one page") and in trials never carried a metric, only false alarms.
SPELLED = {
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}

_NUMBER = re.compile(
    r"(?<![\w.])"  # not glued to a preceding letter/digit: skips the 8 in YOLOv8
    rf"(?:(?P<word>{'|'.join(APPROX_WORDS)})\s+)?"
    r"(?P<pre>[~$]?)"
    rf"(?P<num>\d+(?:,\d{{3}})*(?:\.\d+)?|{'|'.join(SPELLED)})"
    r"(?P<suf>[KkMm]?\+?%?)"
    r"(?!\w|\.\d)"  # not glued to a following letter: skips the 3 in 3D
    # The next few words, looked at but not consumed, so a later spelled-out
    # number ("~6 missions and two drones") is still found on its own.
    r"(?=(?P<after>(?:[\s-]+[A-Za-z][A-Za-z.]*){0,4}))",
    re.IGNORECASE,
)

# Words that join phrases rather than name a unit. After a run of names
# ("500+ GitHub repos through"), reaching one means the number has no unit.
_FUNCTION_WORDS = frozenset(
    "a an the of in on at to for per with across through from by and or into over via "
    "while during than".split()
)

# Abbreviations mean the same unit as their full word ("5+ min" for "5+ minutes").
_UNIT_ALIASES = {
    "min": "minute", "mins": "minute", "hr": "hour", "hrs": "hour", "sec": "second",
    "secs": "second", "wk": "week", "wks": "week", "mo": "month", "mos": "month",
    "yr": "year", "yrs": "year",
}  # fmt: skip


def _unit(after: str) -> str:
    """The words naming what a number counts, e.g. "overnight survey flights".

    Units are common nouns, so leading names and acronyms are skipped ("~20 Example Club
    attendees", "~8 FAA inspectors"). The phrase is the run of lowercase words after
    them, ending at a word that only joins phrases, at a name, or at punctuation.
    """
    phrase: list[str] = []
    for word in re.findall(r"[A-Za-z][A-Za-z.]*", after):
        if word[0].isupper():
            if phrase:
                break
            continue
        if word.lower() in _FUNCTION_WORDS:
            break
        phrase.append(word.lower())
    return " ".join(phrase)


def _unit_stem(word: str) -> str:
    """Compare units by meaning: "min" and "minutes" -> "minute", "hours" -> "hour"."""
    word = _UNIT_ALIASES.get(word, word)
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


@dataclass(frozen=True)
class Number:
    raw: str  # as written, e.g. "approximately 1,000"
    key: str  # what must match, e.g. "~1000": marker, symbols and digits
    digits: str  # just the value, e.g. "1000", for "closest match" hints
    unit: str  # the words naming what is counted, lowercased; "" if none


@dataclass
class NumberCheck:
    failures: list[str] = field(default_factory=list)  # block the bullet
    flags: list[str] = field(default_factory=list)  # shown for review, never block

    @property
    def ok(self) -> bool:
        return not self.failures


def _blank_out(text: str, names: Iterable[str]) -> str:
    # Longest first, so "Claude Sonnet 4.6" goes before a shorter "Sonnet 4.6".
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text, flags=re.IGNORECASE)
    return text


def extract_numbers(text: str, tech_names: Iterable[str] = ()) -> list[Number]:
    """Every real number in `text`, ignoring the digits inside known tech names."""
    found = []
    for m in _NUMBER.finditer(_blank_out(text, tech_names)):
        num = m["num"].lower()
        digits = SPELLED.get(num, num.replace(",", ""))
        approx = "~" if (m["word"] or m["pre"] == "~") else ""
        dollar = "$" if m["pre"] == "$" else ""
        key = f"{approx}{dollar}{digits}{m['suf'].upper()}"
        raw = m.group(0)[: m.end("suf") - m.start()].strip()
        found.append(Number(raw=raw, key=key, digits=digits, unit=_unit(m["after"])))
    return found


def check_numbers(
    text: str, metric_texts: Iterable[str], tech_names: Iterable[str] = ()
) -> NumberCheck:
    """Compare a bullet's numbers with the metrics it cites.

    A number fails unless the same value appears in a metric with the same
    estimate marker (~, +) and symbols ($, %, K). A unit word the metrics never
    use is only flagged: rewording "attendees" as "students" is the writer's job.
    """
    tech_names = list(tech_names)
    metric_texts = list(metric_texts)
    allowed = [n for t in metric_texts for n in extract_numbers(t, tech_names)]
    allowed_keys = {n.key for n in allowed}
    metric_units = {_unit_stem(w) for w in re.findall(r"[a-z]+", " ".join(metric_texts).lower())}

    result = NumberCheck()
    for n in extract_numbers(text, tech_names):
        if n.key not in allowed_keys:
            closest = sorted({a.raw for a in allowed if a.digits == n.digits})
            hint = f" (closest: {', '.join(repr(c) for c in closest)})" if closest else ""
            result.failures.append(f"{n.raw!r} is not in its metrics{hint}")
        # The unit noun may follow describing words ("~6 overnight survey
        # missions"), so the phrase passes if any of its words is a metric's unit.
        elif n.unit and not {_unit_stem(w) for w in n.unit.split()} & metric_units:
            result.flags.append(f"{n.raw!r} is followed by {n.unit!r}, which its metrics never use")
    return result
