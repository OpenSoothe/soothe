"""RFC-105 / IG-543: Stateless helpers for progressive skill disclosure."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import pathspec

from soothe.skills.index import SkillIndexEntry

DiscoverVia = Literal["path", "search", "explicit"]

DEFAULT_CORE_SKILL_NAMES: frozenset[str] = frozenset(
    {"weather", "github", "clawhub", "skill-creator"}
)


def resolve_core_skill_names(core_skills: Sequence[str] | None) -> frozenset[str]:
    """Return configured core skill names or built-in defaults."""
    if core_skills:
        return frozenset(n.lower() for n in core_skills)
    return DEFAULT_CORE_SKILL_NAMES


def _normalize_patterns(patterns: Sequence[str]) -> list[str]:
    """Strip trailing ``/**`` and collapse all-``**`` to empty (unconditional)."""
    out: list[str] = []
    for p in patterns:
        p = p.strip()
        if not p:
            continue
        if p in ("**", "**/*"):
            return []  # all-** treated as unconditional
        if p.endswith("/**"):
            p = p[:-3]
        out.append(p)
    return out


def _is_unconditional(entry: SkillIndexEntry) -> bool:
    """Legacy: skill has no path patterns (pre-IG-543 partition)."""
    if entry.paths is None:
        return True
    normalized = _normalize_patterns(entry.paths)
    return not normalized


def is_core_skill(entry: SkillIndexEntry, core_names: frozenset[str]) -> bool:
    """Return True when *entry* belongs to the always-listed core tier."""
    if entry.core is False:
        return False
    if entry.name.lower() in core_names:
        return True
    if entry.core is True:
        return True
    return entry.source == "builtin"


class ProgressiveSkillRegistry:
    """Stateless facade. All state lives in caller-owned *activation_state* dict."""

    @staticmethod
    def init_activation_state() -> dict[str, Any]:
        """Return an empty activation_state dict in the canonical shape."""
        return {
            "sent": set(),
            "activated": set(),
            "invoked": set(),
            "invoked_bodies": {},
            "just_invoked": set(),
            "intent_prefetched": False,
        }

    @staticmethod
    def snapshot_activation_state(activation_state: dict[str, Any]) -> dict[str, Any]:
        """Return a graph-safe copy for ``Command.update`` (no transient keys)."""
        return {
            "sent": _coerce_name_set(activation_state.get("sent")),
            "activated": _coerce_name_set(activation_state.get("activated")),
            "invoked": _coerce_name_set(activation_state.get("invoked")),
            "invoked_bodies": dict(activation_state.get("invoked_bodies") or {}),
            "just_invoked": set(),
            "intent_prefetched": bool(activation_state.get("intent_prefetched")),
        }

    def partition_core_deferred(
        self,
        entries: Sequence[SkillIndexEntry],
        core_names: frozenset[str],
    ) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]:
        """Split entries into (core, deferred) listing tiers."""
        core: list[SkillIndexEntry] = []
        deferred: list[SkillIndexEntry] = []
        for entry in entries:
            (core if is_core_skill(entry, core_names) else deferred).append(entry)
        return core, deferred

    def partition(
        self, entries: Sequence[SkillIndexEntry]
    ) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]:
        """Legacy split into (unconditional, conditional) for path matching."""
        unconditional, conditional = [], []
        for entry in entries:
            (unconditional if _is_unconditional(entry) else conditional).append(entry)
        return unconditional, conditional

    def deferred_with_paths(self, deferred: Sequence[SkillIndexEntry]) -> list[SkillIndexEntry]:
        """Return deferred skills that declare ``paths:`` auto-discovery patterns."""
        out: list[SkillIndexEntry] = []
        for entry in deferred:
            if entry.paths is None:
                continue
            if _normalize_patterns(entry.paths):
                out.append(entry)
        return out

    def search_deferred(
        self,
        query: str,
        deferred: Sequence[SkillIndexEntry],
        *,
        discovered: set[str],
        limit: int = 10,
    ) -> list[SkillIndexEntry]:
        """Substring search over deferred skills not yet discovered."""
        q = query.strip().lower()
        if not q:
            return []
        scored: list[tuple[int, SkillIndexEntry]] = []
        for entry in deferred:
            if entry.name in discovered:
                continue
            hay = f"{entry.name} {entry.description} {entry.tags}".lower()
            if q in hay:
                scored.append((hay.index(q), entry))
        scored.sort(key=lambda item: (item[0], item[1].name.lower()))
        return [entry for _, entry in scored[:limit]]

    def match_deferred_in_corpus(
        self,
        text: str,
        deferred: Sequence[SkillIndexEntry],
        *,
        discovered: set[str],
        limit: int = 10,
    ) -> list[SkillIndexEntry]:
        """Match deferred skills whose names appear in ``text`` (turn-0 intent prefetch)."""
        corpus = text.strip().lower()
        if not corpus:
            return []
        scored: list[tuple[int, SkillIndexEntry]] = []
        for entry in deferred:
            if entry.name in discovered:
                continue
            name = entry.name.lower()
            if name in corpus:
                scored.append((corpus.index(name), entry))
        scored.sort(key=lambda item: (item[0], item[1].name.lower()))
        return [entry for _, entry in scored[:limit]]

    def discover(
        self,
        activation_state: dict[str, Any],
        names: Iterable[str],
        *,
        via: DiscoverVia,
    ) -> list[str]:
        """Mark skill names as discovered (stored in ``activated``).

        Returns:
            Names newly added (idempotent).
        """
        del via  # reserved for telemetry / events
        activated = activation_state.setdefault("activated", set())
        if not isinstance(activated, set):
            activated = set(activated)
            activation_state["activated"] = activated
        newly: list[str] = []
        for name in names:
            token = str(name).strip()
            if not token or token in activated:
                continue
            activated.add(token)
            newly.append(token)
        return newly

    def new_for_thread(
        self,
        activation_state: dict[str, Any],
        candidates: Sequence[SkillIndexEntry],
    ) -> list[SkillIndexEntry]:
        """Return entries whose names are not yet in ``activation_state['sent']``."""
        sent = activation_state.get("sent", set())
        if not isinstance(sent, set):
            sent = set(sent)
        names_in_catalog = {entry.name for entry in candidates}
        activation_state["sent"] = {name for name in sent if name in names_in_catalog}
        sent = activation_state["sent"]
        return [entry for entry in candidates if entry.name not in sent]

    def match_paths(
        self,
        activation_state: dict[str, Any],
        workspace: Path,
        file_paths: Sequence[str],
        conditional_skills: Sequence[SkillIndexEntry],
    ) -> list[tuple[str, str, str]]:
        """Return [(skill_name, matched_path, pattern), ...] for newly-activated skills."""
        activated = activation_state.setdefault("activated", set())
        if not isinstance(activated, set):
            activated = set(activated)
            activation_state["activated"] = activated
        newly: list[tuple[str, str, str]] = []
        rel_paths: list[str] = []
        for raw_path in file_paths:
            path = Path(raw_path)
            if not path.is_absolute():
                rel_paths.append(str(path))
            else:
                try:
                    rel_paths.append(str(path.resolve().relative_to(workspace.resolve())))
                except ValueError:
                    continue

        for skill in conditional_skills:
            if skill.name in activated:
                continue
            patterns = _normalize_patterns(skill.paths or ())
            if not patterns:
                continue
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
            for rel_path in rel_paths:
                if spec.match_file(rel_path):
                    newly.append((skill.name, rel_path, patterns[0]))
                    break
        return newly

    def mark_sent(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        activation_state.setdefault("sent", set()).update(names)

    def mark_activated(self, activation_state: dict[str, Any], names: Iterable[str]) -> None:
        self.discover(activation_state, names, via="path")

    def mark_invoked(self, activation_state: dict[str, Any], name: str, body: str) -> None:
        activation_state.setdefault("invoked", set()).add(name)
        activation_state.setdefault("invoked_bodies", {})[name] = body
        activation_state.setdefault("just_invoked", set()).add(name)

    def cache_body(self, activation_state: dict[str, Any], name: str, body: str) -> None:
        activation_state.setdefault("invoked_bodies", {})[name] = body


def _coerce_name_set(value: Any) -> set[str]:
    if isinstance(value, set):
        return {str(item) for item in value}
    if isinstance(value, (list, tuple)):
        return {str(item) for item in value}
    return set()
