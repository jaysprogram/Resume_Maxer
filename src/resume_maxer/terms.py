"""Words a bullet took from the job posting that its own facts never use.

Measurement only; review.py reports them as flags. The agreed design lets the
writer use the posting's vocabulary ("agile", "AI automation") where the facts
support it; this lists every such word so a person can confirm it is true.
"""

import re
from collections.abc import Iterable

from resume_maxer.resume_doc import DocBullet, DocEntry
from resume_maxer.schema import Master

# A token keeps the punctuation tech names use: C#, CI/CD, .NET, Node.js, C++.
_TOKEN = re.compile(r"[A-Za-z.][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Za-z]")


def _norm(token: str) -> str:
    word = token.lower().strip(".-/")
    # Plurals: "dashboards" is "dashboard". Not short words, and not endings that
    # are not plurals: "process", "continuous", "analysis".
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    return word


# Words too common in resumes and postings to say anything about a claim.
# A borrowed word on this list is never flagged. Normalized like every other
# word, so "technologies" matches its normalized form.
STOPWORDS = frozenset(
    _norm(w)
    for w in """
    a about across after all also an and any are as at be been being both but by can
    each for from has have how in into is it its more most of on one or our out over
    per same so such than that the their them then these this those through to under
    up using via was were what when where which while who will with within without you
    your we us our i me my they them he she his her it


    build built building create created creating deliver delivered design designed
    designing develop developed developing drive driven enable enabled enhance help
    helped implement implemented improve improved lead led make made manage managed
    own owned provide provided run ran ship shipped support supported use used work
    worked working write wrote written

    app application applications data development engineer engineering experience new
    product products project projects real role solution solutions system systems
    team teams technical technology technologies time tool tools user users way
    """.split()
)


def _spellings(text: str) -> dict[str, str]:
    """Normalized content word -> its first spelling in `text`, in order."""
    found: dict[str, str] = {}
    for token in _TOKEN.findall(text):
        word = _norm(token)
        if len(word) > 1 and word not in STOPWORDS:
            found.setdefault(word, token.strip(".-/"))
    return found


def words(text: str) -> list[str]:
    """Normalized content words of `text`, in order, without repeats."""
    return list(_spellings(text))


def backing_text(entry: DocEntry, bullet: DocBullet, master: Master) -> str:
    """Everything the master says that this bullet may draw words from."""
    entries = {e.id: e for e in master.entries}
    by_id = {b.id: b for e in master.entries for b in e.bullets}
    source = entries[entry.entry_id]
    parts = [source.name, *source.stack, *source.notes]
    if source.title:
        parts.append(source.title.value)
    for bullet_id in bullet.source_ids:
        fact = by_id.get(bullet_id)
        if fact is None:
            continue
        parts += [v.text for v in fact.variants.values()] + fact.tags + fact.notes
        parts += [master.metrics[m].text for m in fact.metrics if m in master.metrics]
    # A skill the facts name may be written as any of its names: a "k8s" tag
    # backs "Kubernetes".
    known = set(words(" ".join(parts)))
    for skill in master.skills:
        names = [skill.name, *skill.aliases]
        if any(set(words(n)) <= known for n in names if words(n)):
            parts += names
    return " ".join(parts)


def borrowed_terms(bullet_text: str, backing: str, posting_words: Iterable[str]) -> list[str]:
    """Words of the bullet that the posting uses and the bullet's facts do not,
    spelled as the bullet spells them."""
    posting, backed = set(posting_words), set(words(backing))
    return [
        spelling
        for word, spelling in _spellings(bullet_text).items()
        if word in posting and word not in backed
    ]
