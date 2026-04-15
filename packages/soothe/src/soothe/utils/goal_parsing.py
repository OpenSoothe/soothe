"""Goal file parsing utilities.

Shared between daemon, TUI, and cognition layers to avoid duplicated
YAML frontmatter parsing logic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split YAML frontmatter from body text.

    Args:
        text: Markdown file content.

    Returns:
        Tuple of (frontmatter_yaml_or_None, body_text).
    """
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:  # noqa: PLR2004
        return None, text
    return parts[1], parts[2]


def parse_goal_text(text: str) -> dict[str, Any] | None:
    """Parse a GOAL.md file into a lightweight dict.

    Args:
        text: File content string.

    Returns:
        Dict with id, description, priority, status, source — or None.
    """
    frontmatter, body = split_frontmatter(text)
    if frontmatter is None:
        return None

    fm: dict[str, Any] = yaml.safe_load(frontmatter) or {}
    body = body.strip()

    desc = next(
        (line.strip()[2:] for line in body.splitlines() if line.strip().startswith("# ")),
        "",
    )

    return {
        "id": fm.get("id", ""),
        "description": desc,
        "priority": fm.get("priority", 50),
        "status": fm.get("status", "pending"),
    }


def parse_autopilot_goals(autopilot_dir: Path) -> list[dict[str, Any]]:
    """Parse all goal files in an autopilot directory.

    Scans GOAL.md, GOALS.md, and goals/*/GOAL.md.

    Args:
        autopilot_dir: Path to the autopilot directory.

    Returns:
        List of goal info dicts.
    """
    goals: list[dict[str, Any]] = []

    # Single GOAL.md
    goal_file = autopilot_dir / "GOAL.md"
    if goal_file.exists():
        parsed = parse_goal_text(goal_file.read_text())
        if parsed:
            goals.append(parsed)

    # GOALS.md — sections delimited by "## Goal:"
    goals_file = autopilot_dir / "GOALS.md"
    if goals_file.exists():
        text = goals_file.read_text()
        for section in re.split(r"## Goal:", text)[1:]:
            parsed = parse_goal_text(f"---\n{section.strip()}")
            if parsed:
                goals.append(parsed)

    # Per-goal subdirectories
    goals_dir = autopilot_dir / "goals"
    if goals_dir.exists():
        for subdir in sorted(goals_dir.iterdir()):
            if subdir.is_dir():
                gfile = subdir / "GOAL.md"
                if gfile.exists():
                    parsed = parse_goal_text(gfile.read_text())
                    if parsed:
                        goals.append(parsed)

    return goals
