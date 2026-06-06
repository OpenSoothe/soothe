"""SkillWarehouse -- scan directories, parse SKILL.md, compute hashes (RFC-0004)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from .models import SkillRecord

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillWarehouse:
    """Scans configured directories for deepagents-compatible skill packages."""

    def __init__(self, paths: list[str]) -> None:
        """Initialize the skill warehouse.

        Args:
            paths: List of directory paths to scan for skill packages.
        """
        self._paths = [Path(p).expanduser().resolve() for p in paths]

    def scan(self) -> list[SkillRecord]:
        """Scan all warehouse paths and return skill records."""
        records: list[SkillRecord] = []
        for base in self._paths:
            if not base.is_dir():
                logger.debug("Warehouse path does not exist: %s", base)
                continue
            for skill_md in base.rglob("SKILL.md"):
                try:
                    record = self._parse_skill(skill_md)
                    records.append(record)
                except Exception:
                    logger.warning("Failed to parse %s", skill_md, exc_info=True)
        return records

    def _parse_skill(self, skill_md: Path) -> SkillRecord:
        """Parse a single SKILL.md into a SkillRecord."""
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
        chash = self.content_hash(content)

        return SkillRecord(
            id=skill_id,
            name=str(name),
            description=str(description),
            path=skill_dir,
            tags=[str(t) for t in tags],
            status="indexed",
            indexed_at=datetime.now(UTC),
            content_hash=chash,
        )

    @staticmethod
    def parse_skill_md(content: str) -> tuple[dict, str]:
        """Parse SKILL.md content into (frontmatter_dict, body_text)."""
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}, content

        try:
            import yaml

            fm = yaml.safe_load(match.group(1)) or {}
        except Exception:
            fm = {}

        body = content[match.end() :]
        return fm, body

    @staticmethod
    def content_hash(content: str) -> str:
        """Compute SHA-256 hex digest of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def path_id(path: str) -> str:
        """Compute a deterministic ID from an absolute path."""
        return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
