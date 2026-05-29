"""RFC-105: Stateless helpers for progressive skill disclosure."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import pathspec

from soothe.skills.index import SkillIndexEntry


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
    if entry.paths is None:
        return True
    normalized = _normalize_patterns(entry.paths)
    return not normalized


class ProgressiveSkillRegistry:
    """Stateless facade. All state lives in caller-owned *activation_state* dict."""

    @staticmethod
    def init_activation_state() -> dict:
        """Return an empty activation_state dict in the canonical shape."""
        return {
            "sent": set(),
            "activated": set(),
            "invoked": set(),
            "invoked_bodies": {},
            "just_invoked": set(),
        }

    def partition(
        self, entries: Sequence[SkillIndexEntry]
    ) -> tuple[list[SkillIndexEntry], list[SkillIndexEntry]]:
        """Split entries into (unconditional, conditional)."""
        unconditional, conditional = [], []
        for e in entries:
            (unconditional if _is_unconditional(e) else conditional).append(e)
        return unconditional, conditional

    def new_for_thread(
        self,
        activation_state: dict,
        candidates: Sequence[SkillIndexEntry],
    ) -> list[SkillIndexEntry]:
        """Return entries whose names are not yet in ``activation_state['sent']``."""
        sent = activation_state.get("sent", set())
        names_in_catalog = {e.name for e in candidates}
        # Prune dangling names (skill removed since last sent)
        activation_state["sent"] = {n for n in sent if n in names_in_catalog}
        sent = activation_state["sent"]
        return [e for e in candidates if e.name not in sent]

    def match_paths(
        self,
        activation_state: dict,
        workspace: Path,
        file_paths: Sequence[str],
        conditional_skills: Sequence[SkillIndexEntry],
    ) -> list[tuple[str, str, str]]:
        """Return [(skill_name, matched_path, pattern), ...] for newly-activated skills."""
        activated = activation_state.setdefault("activated", set())
        newly: list[tuple[str, str, str]] = []
        rel_paths: list[str] = []
        for p in file_paths:
            path = Path(p)
            if not path.is_absolute():
                rel_paths.append(str(path))
            else:
                try:
                    rel_paths.append(str(path.resolve().relative_to(workspace.resolve())))
                except ValueError:
                    continue  # path outside workspace → reject

        for skill in conditional_skills:
            if skill.name in activated:
                continue
            patterns = _normalize_patterns(skill.paths or ())
            if not patterns:
                continue
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
            for rp in rel_paths:
                if spec.match_file(rp):
                    newly.append((skill.name, rp, patterns[0]))
                    break
        return newly

    def mark_sent(self, activation_state: dict, names: Iterable[str]) -> None:
        activation_state.setdefault("sent", set()).update(names)

    def mark_activated(self, activation_state: dict, names: Iterable[str]) -> None:
        activation_state.setdefault("activated", set()).update(names)

    def mark_invoked(self, activation_state: dict, name: str, body: str) -> None:
        activation_state.setdefault("invoked", set()).add(name)
        activation_state.setdefault("invoked_bodies", {})[name] = body
        activation_state.setdefault("just_invoked", set()).add(name)

    def cache_body(self, activation_state: dict, name: str, body: str) -> None:
        activation_state.setdefault("invoked_bodies", {})[name] = body
