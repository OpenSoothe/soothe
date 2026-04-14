"""Agent skill catalog: discovery and invocation envelopes (daemon + TUI shared).

Paths and ``SKILL.md`` loading for catalog resolution run on the host that owns
the agent config (daemon server for remote-safe flows).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, NamedTuple, TypedDict

import yaml

from soothe.config import SootheConfig
from soothe.skills import get_built_in_skills_paths

logger = logging.getLogger(__name__)


class SkillDirectoryMeta(TypedDict, total=False):
    """One skill directory resolved from built-ins or ``SootheConfig.skills``."""

    name: str
    description: str
    path: str
    source: str
    version: str


class SkillWireEntry(TypedDict, total=False):
    """Wire-safe skill row (no filesystem paths)."""

    name: str
    description: str
    source: str
    version: str


class SkillInvocationEnvelope(NamedTuple):
    """Prompt and optional LangChain message fields for a skill turn."""

    prompt: str
    message_kwargs: dict[str, Any] | None = None


def strip_skill_frontmatter(text: str) -> str:
    """Remove YAML frontmatter delimited by ``---`` markers from SKILL.md text."""
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return text
    end = stripped.find("\n---", 3)
    if end == -1:
        return text
    after = end + 4  # len("\n---")
    return stripped[after:].lstrip("\n")


def _split_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text
    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_raw = stripped[3:end].strip()
    body = stripped[end + 4 :].lstrip("\n")
    try:
        loaded = yaml.safe_load(fm_raw)
    except yaml.YAMLError:
        logger.debug("Invalid YAML frontmatter in SKILL.md", exc_info=True)
        return {}, body
    if not isinstance(loaded, dict):
        return {}, body
    return loaded, body


def parse_skill_directory(skill_dir: Path, *, source: str) -> SkillDirectoryMeta | None:
    """Load metadata for one skill directory (must contain ``SKILL.md``)."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read SKILL.md at %s", skill_md, exc_info=True)
        return None

    meta, _ = _split_yaml_frontmatter(text)
    name_raw = meta.get("name")
    name = str(name_raw).strip().lower() if name_raw is not None else skill_dir.name.strip().lower()
    if not name:
        return None

    desc_val = meta.get("description", "")
    description = str(desc_val).strip() if desc_val is not None else ""

    out: SkillDirectoryMeta = {
        "name": name,
        "description": description,
        "path": str(skill_dir.resolve()),
        "source": source,
    }
    ver_val = meta.get("version")
    if ver_val is not None and str(ver_val).strip():
        out["version"] = str(ver_val).strip()
    return out


def _register_skill_dir(by_name: "OrderedDict[str, SkillDirectoryMeta]", skill_dir: Path, source: str) -> None:
    meta = parse_skill_directory(skill_dir, source=source)
    if meta is not None and meta.get("name"):
        by_name[meta["name"]] = meta


def _ingest_config_path(by_name: "OrderedDict[str, SkillDirectoryMeta]", root: Path, source: str) -> None:
    root = root.expanduser().resolve()
    if not root.exists():
        return
    if (root / "SKILL.md").is_file():
        _register_skill_dir(by_name, root, source=source)
        return
    if not root.is_dir():
        return
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        logger.warning("Could not list skill root %s", root, exc_info=True)
        return
    for child in children:
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").is_file():
            continue
        _register_skill_dir(by_name, child, source=source)


def skill_catalog_by_name(config: SootheConfig) -> "OrderedDict[str, SkillDirectoryMeta]":
    """Build name → metadata map matching agent ``create_deep_agent`` skill path merge.

    Order: each built-in skill directory (``get_built_in_skills_paths()``), then
    each entry in ``config.skills``. Later entries override same ``name``.

    Args:
        config: Loaded ``SootheConfig`` for the daemon or local agent.

    Returns:
        Ordered map of canonical skill name to directory metadata.
    """
    by_name: OrderedDict[str, SkillDirectoryMeta] = OrderedDict()

    for p in get_built_in_skills_paths():
        _ingest_config_path(by_name, Path(p), source="builtin")

    for raw in config.skills or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        _ingest_config_path(by_name, Path(raw), source="config")

    return by_name


def list_skills_for_agent_config(config: SootheConfig) -> list[SkillDirectoryMeta]:
    """Return all skills visible to the agent graph for this config."""
    return list(skill_catalog_by_name(config).values())


def wire_entries_for_agent_config(config: SootheConfig) -> list[SkillWireEntry]:
    """Return wire-safe rows (no paths) sorted by name."""
    rows: list[SkillWireEntry] = []
    for m in list_skills_for_agent_config(config):
        row: SkillWireEntry = {"name": m["name"], "description": m.get("description", "")}
        if m.get("source"):
            row["source"] = m["source"]
        if m.get("version"):
            row["version"] = m["version"]
        rows.append(row)
    rows.sort(key=lambda r: r["name"])
    return rows


def resolve_skill_directory(config: SootheConfig, skill_name: str) -> SkillDirectoryMeta | None:
    """Resolve a skill by canonical name (case-insensitive)."""
    key = skill_name.strip().lower()
    if not key:
        return None
    return skill_catalog_by_name(config).get(key)


def read_skill_markdown(meta: SkillDirectoryMeta) -> str | None:
    """Read full ``SKILL.md`` text for a resolved catalog entry."""
    skill_md = Path(meta["path"]) / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        return skill_md.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Could not read SKILL.md at %s", skill_md, exc_info=True)
        return None


def build_skill_invocation_envelope(
    cached: SkillDirectoryMeta,
    skill_markdown: str,
    args: str,
) -> SkillInvocationEnvelope:
    """Compose the user-visible prompt and optional message metadata for a skill."""
    body = strip_skill_frontmatter(skill_markdown).strip()
    name = cached.get("name", "")
    description = cached.get("description", "").strip()
    desc_line = f"Summary: {description}\n\n" if description else ""

    user_block = (
        args.strip()
        if args.strip()
        else "(No extra user text — infer what to remember from the conversation and proceed.)"
    )

    prompt = (
        f"You are running the Soothe skill `{name}`.\n\n"
        f"{desc_line}"
        "## Skill instructions\n\n"
        f"{body}\n\n"
        "## User request\n\n"
        f"{user_block}\n"
    )

    message_kwargs: dict[str, Any] = {
        "additional_kwargs": {
            "soothe_skill": name,
            "soothe_skill_source": cached.get("source", ""),
        }
    }

    return SkillInvocationEnvelope(prompt=prompt, message_kwargs=message_kwargs)
