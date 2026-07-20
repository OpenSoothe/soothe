"""Corpus matching helpers for skill name/tag prefetch (RFC-105)."""

from __future__ import annotations

import re

# User-facing phrasings for built-in core skills (name → extra match tokens).
BUILTIN_SKILL_ALIASES: dict[str, frozenset[str]] = {
    "clawhub": frozenset(
        {
            "claw hub",
            "claw hub registry",
            "clawhub registry",
            "community skill registry",
        }
    ),
    "github": frozenset(
        {
            "git hub",
            "github cli",
            "gh cli",
        }
    ),
    "skill-creator": frozenset(
        {
            "skill creator",
            "create skill",
            "create a skill",
            "new skill",
            "write skill",
            "agentskill",
            "skill authoring",
        }
    ),
    "weather": frozenset(
        {
            "wttr",
            "wttr.in",
        }
    ),
}

_COMPACT_RE = re.compile(r"[\s\-_]+")
# Tags this length or shorter require token boundaries (avoids ``pr`` in ``prior``).
_SHORT_BOUNDARY_MAX_LEN = 3
_BOUNDARY_BEFORE = r"(?<![a-z0-9])"
_BOUNDARY_AFTER = r"(?![a-z0-9])"


def _compact(text: str) -> str:
    """Collapse spaces, hyphens, and underscores for compound-name matching."""
    return _COMPACT_RE.sub("", text.lower())


def _direct_substring_index(corpus: str, variant: str) -> int | None:
    if len(variant) < 2:
        return None
    if len(variant) <= _SHORT_BOUNDARY_MAX_LEN:
        pattern = rf"{_BOUNDARY_BEFORE}{re.escape(variant)}{_BOUNDARY_AFTER}"
        match = re.search(pattern, corpus)
        return match.start() if match else None
    pos = corpus.find(variant)
    return pos if pos >= 0 else None


def _compact_substring_index(corpus: str, token: str) -> int | None:
    """Match ``token`` against ``corpus`` after compacting both sides."""
    compact_token = _compact(token)
    if len(compact_token) < 4:
        return None
    compact_corpus = _compact(corpus)
    pos = compact_corpus.find(compact_token)
    if pos < 0:
        return None
    return _compact_index_to_corpus_index(corpus, pos)


def _compact_index_to_corpus_index(corpus: str, compact_index: int) -> int:
    """Map an index in ``compact(corpus)`` back to an index in ``corpus``."""
    ci = 0
    for i, ch in enumerate(corpus):
        if ch.isspace() or ch in "-_":
            continue
        if ci == compact_index:
            return i
        ci += 1
    return len(corpus)


def match_variants_for_token(token: str, *, skill_name: str | None = None) -> tuple[str, ...]:
    """Return lowercase variants used when matching a skill name or tag in user text."""
    base = token.strip().lower()
    if not base:
        return ()
    variants: list[str] = [base]
    if "-" in base:
        variants.append(base.replace("-", " "))
        variants.append(base.replace("-", ""))
    if skill_name and base == skill_name.lower():
        variants.extend(BUILTIN_SKILL_ALIASES.get(skill_name.lower(), ()))
    seen: set[str] = set()
    out: list[str] = []
    for variant in variants:
        if len(variant) >= 2 and variant not in seen:
            seen.add(variant)
            out.append(variant)
    return tuple(out)


def earliest_corpus_match(
    corpus: str,
    token: str,
    *,
    skill_name: str | None = None,
) -> int | None:
    """Return the earliest start index where ``token`` matches ``corpus``, or ``None``.

    Handles hyphen/space variants (``skill-creator`` ↔ ``skill creator``) and compact
    forms (``clawhub`` ↔ ``claw hub``) so built-in skills auto-invoke on natural phrasing.
    """
    corpus_l = corpus.strip().lower()
    if not corpus_l:
        return None

    best: int | None = None
    for variant in match_variants_for_token(token, skill_name=skill_name):
        pos = _direct_substring_index(corpus_l, variant)
        if pos is not None:
            best = pos if best is None else min(best, pos)

    compact_pos = _compact_substring_index(corpus_l, token)
    if compact_pos is not None:
        best = compact_pos if best is None else min(best, compact_pos)

    return best
