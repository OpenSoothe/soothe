"""Skills discovery and invocation helpers for the Soothe Textual TUI."""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any, NamedTuple

from soothe.skills import get_built_in_skills_paths
from soothe.ux.tui.config import Settings, _get_settings
from soothe.ux.tui.skills.load import (
    ExtendedSkillMetadata,
    parse_skill_directory,
    strip_skill_frontmatter,
)

logger = logging.getLogger(__name__)


class SkillInvocationEnvelope(NamedTuple):
    """Prompt and optional LangChain message fields for a skill turn."""

    prompt: str
    message_kwargs: dict[str, Any] | None = None


def discover_skills_and_roots(assistant_id: str) -> tuple[list[ExtendedSkillMetadata], list[Path]]:
    """Discover skills and build containment roots for ``load_skill_content``.

    Scans, in order: built-in package skills, per-agent ``SOOTHE_HOME`` skills,
    project ``.soothe/skills``, ``~/.agents/skills`` / project ``.agents/skills``,
    and optional Claude Code bridge directories. Later locations override
    earlier entries on **name** collisions (user/project win over built-in).

    Args:
        assistant_id: Agent / assistant id used for ``~/SOOTHE_HOME/<id>/skills``.

    Returns:
        Tuple of ``(skills, allowed_roots)`` where ``skills`` is ordered by
        ascending precedence (built-in first, winning entry last), and
        ``allowed_roots`` lists every resolved directory that may legally contain
        a ``SKILL.md`` for loading (including ``settings.extra_skills_dirs``).
    """
    settings = _get_settings()
    by_name: "OrderedDict[str, ExtendedSkillMetadata]" = OrderedDict()

    # Package built-ins: `get_built_in_skills_paths()` returns one directory per
    # skill (each already contains SKILL.md), not a parent containing subfolders.
    for p in get_built_in_skills_paths():
        skill_dir = Path(p).resolve()
        meta = parse_skill_directory(skill_dir, source="builtin")
        if meta is not None and meta.get("name"):
            by_name[meta["name"]] = meta

    roots_scan: list[tuple[Path, str]] = [
        (settings.get_user_skills_dir(assistant_id), "user"),
    ]

    proj_soothe = settings.get_project_skills_dir()
    if proj_soothe is not None:
        roots_scan.append((proj_soothe, "project"))

    roots_scan.append((settings.get_user_agent_skills_dir(), "agents"))

    proj_agents = settings.get_project_agent_skills_dir()
    if proj_agents is not None:
        roots_scan.append((proj_agents, "agents"))

    roots_scan.append((Settings.get_user_claude_skills_dir(), "claude"))

    proj_claude = settings.get_project_claude_skills_dir()
    if proj_claude is not None:
        roots_scan.append((proj_claude, "claude"))

    for root, source in roots_scan:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            logger.warning("Could not list skill root %s", root, exc_info=True)
            continue
        for child in children:
            if not child.is_dir():
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            meta = parse_skill_directory(child, source=source)
            if meta is None or not meta.get("name"):
                continue
            by_name[meta["name"]] = meta

    skills = list(by_name.values())

    allowed: list[Path] = []
    seen: set[Path] = set()
    for meta in skills:
        p = Path(meta["path"]).resolve()
        if p not in seen:
            seen.add(p)
            allowed.append(p)
    for extra in settings.get_extra_skills_dirs():
        rp = extra.resolve()
        if rp not in seen:
            seen.add(rp)
            allowed.append(rp)

    return skills, allowed


def build_skill_invocation_envelope(
    cached: ExtendedSkillMetadata,
    skill_markdown: str,
    args: str,
) -> SkillInvocationEnvelope:
    """Compose the user-visible prompt and optional message metadata for a skill.

    Args:
        cached: Discovery record for the skill.
        skill_markdown: Full ``SKILL.md`` contents (including frontmatter).
        args: Text after ``/skill:name`` or ``/remember`` (may be empty).

    Returns:
        ``SkillInvocationEnvelope`` with the composed prompt and kwargs suitable
        for ``SootheApp._send_to_agent``.
    """
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
