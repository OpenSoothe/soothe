"""Mtime-based skill index for fast daemon-level skill discovery.

Indexes skills under ``~/.agents/skills``, package-bundled
``skills/builtin_skills/``, and ``~/.soothe/skills``.
Uses stat-only invalidation: re-parses SKILL.md only when mtime changes.
Persists cache to ~/.soothe/cache/skill_index.json for fast restarts.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_FILE = Path.home() / ".soothe" / "cache" / "skill_index.json"

# Package-bundled built-in skills directory
_BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "builtin_skills"

# (root_path, source_label) — order matters: later roots win on name collision
_SKILL_ROOTS: tuple[tuple[Path, str], ...] = (
    (Path.home() / ".agents" / "skills", "user"),
    (_BUILTIN_SKILLS_DIR, "builtin"),
    (Path.home() / ".soothe" / "skills", "user"),
)


def _parse_core_frontmatter(raw: object) -> bool | None:
    """Parse optional ``core:`` frontmatter scalar."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        token = raw.strip().lower()
        if token in ("true", "yes", "1"):
            return True
        if token in ("false", "no", "0"):
            return False
    return None


@dataclass(frozen=True, slots=True)
class SkillIndexEntry:
    """Lightweight skill metadata cached by the index."""

    name: str
    description: str
    tags: str
    source: str  # "user"
    path: str
    mtime: float
    paths: tuple[str, ...] | None = None  # RFC-105: conditional activation patterns
    when_to_use: str | None = None  # RFC-105: multi-line guidance for listing
    core: bool | None = None  # IG-543: True=core tier, False=deferred, None=inherit


@dataclass
class SkillIndex:
    """Mtime-aware skill index that avoids re-parsing unchanged SKILL.md files.

    The index scans community, built-in, and user skill directories.
    When a skill name appears in multiple roots, the later root wins
    (``~/.soothe/skills`` > built-ins > ``~/.agents/skills``).
    Workspace/project skills are resolved by the loop at runtime.
    """

    _entries: dict[str, SkillIndexEntry] = field(default_factory=dict)
    _loaded: bool = field(default=False)

    def entries(self) -> list[SkillIndexEntry]:
        """Return all indexed entries sorted by name."""
        self._ensure_loaded()
        return sorted(self._entries.values(), key=lambda e: e.name.lower())

    def resolve(self, name: str) -> SkillIndexEntry | None:
        """Resolve a skill by name (case-insensitive)."""
        self._ensure_loaded()
        return self._entries.get(name.lower())

    def rebuild_if_stale(self) -> list[SkillIndexEntry]:
        """Stat all skill directories; re-parse only changed entries.

        Returns the full list of current entries after refresh.
        """
        current_skills = self._discover_skill_dirs()
        changed = False

        new_entries: dict[str, SkillIndexEntry] = {}
        for key, (skill_dir, mtime, source) in current_skills.items():
            existing = self._entries.get(key)
            if existing and existing.mtime >= mtime and existing.path == str(skill_dir):
                new_entries[key] = existing
            else:
                entry = self._parse_skill_dir(skill_dir, mtime, source=source)
                if entry:
                    new_entries[entry.name.lower()] = entry
                    changed = True

        if set(self._entries.keys()) != set(new_entries.keys()):
            changed = True

        self._entries = new_entries
        self._loaded = True

        if changed:
            self._persist()

        return self.entries()

    def wire_entries(self) -> list[dict[str, Any]]:
        """Return wire-safe dicts (no path) for RPC serialization."""
        result: list[dict[str, Any]] = []
        for entry in self.entries():
            d: dict[str, Any] = {
                "name": entry.name,
                "description": entry.description,
                "source": entry.source,
            }
            if entry.tags:
                d["tags"] = entry.tags
            if entry.paths is not None:
                d["paths"] = list(entry.paths)
            if entry.when_to_use is not None:
                d["when_to_use"] = entry.when_to_use
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load_cache()
            self.rebuild_if_stale()

    def _discover_skill_dirs(self) -> dict[str, tuple[Path, float, str]]:
        """Stat SKILL.md in each candidate dir; return name key → (path, mtime, source).

        When the same skill name exists in multiple roots, the later root wins
        (last-wins dedup). ``~/.soothe/skills`` overrides built-ins which
        override ``~/.agents/skills``.
        """
        by_name: dict[str, tuple[Path, float, str]] = {}
        for root, source in _SKILL_ROOTS:
            if not root.is_dir():
                continue
            try:
                entries = os.scandir(root)
            except OSError:
                continue
            with entries:
                for dir_entry in entries:
                    if not dir_entry.is_dir(follow_symlinks=True):
                        continue
                    skill_md = Path(dir_entry.path) / "SKILL.md"
                    try:
                        st = skill_md.stat()
                    except OSError:
                        continue
                    skill_name_key = self._discover_skill_name_key(skill_md, dir_entry.name)
                    by_name[skill_name_key] = (
                        Path(dir_entry.path).resolve(),
                        st.st_mtime,
                        source,
                    )
        return by_name

    def _discover_skill_name_key(self, skill_md: Path, fallback_dir_name: str) -> str:
        """Return lowercase dedupe key from frontmatter ``name`` when available."""
        fallback = str(fallback_dir_name).strip().lower()
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            return fallback
        try:
            from soothe_nano.skills.catalog import _parse_frontmatter

            fm = _parse_frontmatter(text)
        except Exception:  # noqa: BLE001
            return fallback
        raw_name = fm.get("name")
        if isinstance(raw_name, str) and raw_name.strip():
            return raw_name.strip().lower()
        return fallback

    def _parse_skill_dir(
        self, skill_dir: Path, mtime: float, *, source: str = "user"
    ) -> SkillIndexEntry | None:
        """Parse SKILL.md frontmatter and build an index entry."""
        md_file = skill_dir / "SKILL.md"
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            return None

        from soothe_nano.skills.catalog import _parse_frontmatter, _strip_frontmatter

        fm = _parse_frontmatter(text)
        name = fm.get("name", skill_dir.name)
        description = fm.get("description", "")
        if not description:
            body = _strip_frontmatter(text)
            for line in body.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    description = stripped.lstrip("#").strip()
                    break
                if stripped:
                    description = stripped
                    break

        return SkillIndexEntry(
            name=name,
            description=description,
            tags=fm.get("tags", ""),
            source=source,
            path=str(skill_dir),
            mtime=mtime,
            paths=tuple(fm["paths"]) if "paths" in fm and isinstance(fm["paths"], list) else None,
            when_to_use=fm.get("when_to_use") or None,
            core=_parse_core_frontmatter(fm.get("core")),
        )

    def _load_cache(self) -> None:
        """Load persisted index from disk if available."""
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return

        if not isinstance(data, list):
            return

        for raw in data:
            try:
                # Tolerate old cache rows missing RFC-105 fields
                raw.setdefault("paths", None)
                raw.setdefault("when_to_use", None)
                raw.setdefault("core", None)
                entry = SkillIndexEntry(**raw)
                self._entries[entry.name.lower()] = entry
            except (TypeError, KeyError):
                continue

    def _persist(self) -> None:
        """Write current index to disk cache."""
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(e) for e in self._entries.values()]
            _CACHE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            logger.debug("Failed to persist skill index cache", exc_info=True)


def _make_wire_entry(entry: SkillIndexEntry) -> dict[str, Any]:
    """Convert an index entry to the wire format expected by existing RPC consumers."""
    d: dict[str, Any] = {
        "name": entry.name,
        "description": entry.description,
        "source": entry.source,
    }
    if entry.tags:
        d["tags"] = entry.tags
    if entry.paths is not None:
        d["paths"] = list(entry.paths)
    if entry.when_to_use is not None:
        d["when_to_use"] = entry.when_to_use
    return d
