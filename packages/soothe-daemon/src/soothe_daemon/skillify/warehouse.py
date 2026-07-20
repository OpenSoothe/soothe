"""Skill warehouse — scan directories, parse SKILL.md, compute hashes."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from soothe_sdk.skillify.models import SkillRecord

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillWarehouse:
    """Scans configured directories for skill packages."""

    def __init__(self, paths: list[str]) -> None:
        self._paths = [Path(p).expanduser().resolve() for p in paths]

    def scan(self) -> list[SkillRecord]:
        """Scan all warehouse paths and return deduped skill records.

        Deduplication is by normalized skill name (frontmatter ``name`` when
        present, otherwise directory name). Later configured paths override
        earlier paths (last-wins).
        """
        by_name: dict[str, SkillRecord] = {}
        for base in self._paths:
            if not base.is_dir():
                logger.debug("Warehouse path does not exist: %s", base)
                continue
            for skill_md in base.rglob("SKILL.md"):
                try:
                    record = self._parse_skill(skill_md)
                except Exception:
                    logger.warning("Failed to parse %s", skill_md, exc_info=True)
                    continue
                key = self._name_key(record.name, fallback=skill_md.parent.name)
                by_name[key] = record
        return list(by_name.values())

    def _parse_skill(self, skill_md: Path) -> SkillRecord:
        content = skill_md.read_text(encoding="utf-8")
        frontmatter, _body = self.parse_skill_md(content)

        name = frontmatter.get("name", skill_md.parent.name)
        description = frontmatter.get("description", "")
        if isinstance(description, str):
            description = description.strip()
        tags_raw = frontmatter.get("tags", [])
        tags = tags_raw if isinstance(tags_raw, list) else []

        skill_dir = str(skill_md.parent.resolve())
        skill_id = self.path_id(skill_dir)
        content_hash = self.content_hash(content)

        return SkillRecord(
            id=skill_id,
            name=str(name),
            description=str(description),
            path=skill_dir,
            tags=[str(tag) for tag in tags],
            status="indexed",
            indexed_at=datetime.now(UTC),
            content_hash=content_hash,
        )

    @staticmethod
    def parse_skill_md(content: str) -> tuple[dict, str]:
        """Parse SKILL.md content into (frontmatter_dict, body_text)."""
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}, content

        try:
            import yaml

            frontmatter = yaml.safe_load(match.group(1)) or {}
        except Exception:
            frontmatter = {}

        body = content[match.end() :]
        return frontmatter, body

    @staticmethod
    def content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def path_id(path: str) -> str:
        return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _name_key(name: str, *, fallback: str) -> str:
        candidate = str(name or "").strip()
        if not candidate:
            candidate = str(fallback or "").strip()
        return candidate.lower()
