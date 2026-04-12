"""Goal status tracking in markdown files (RFC-200 §339, IG-155)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


def update_goal_status(
    goal_md: Path,
    status: str,
    error: str | None = None,
) -> None:
    """Update goal status in GOAL.md frontmatter (IG-155).

    Args:
        goal_md: Path to GOAL.md file
        status: New status (pending, active, completed, failed)
        error: Error message (if failed)
    """
    content = goal_md.read_text()

    # Split frontmatter and body
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_yaml = parts[1].strip()
            body = parts[2].strip()

            # Update frontmatter
            updated_frontmatter = update_yaml_frontmatter(
                frontmatter_yaml,
                {"status": status, "error": error or "", "updated_at": datetime.now(UTC).isoformat()},
            )

            # Write back
            updated_content = "---\n" + updated_frontmatter + "\n---\n" + body
            goal_md.write_text(updated_content)

            logger.info("Updated goal %s status to %s", goal_md, status)
            return

    # No frontmatter: add it
    logger.warning("GOAL.md missing frontmatter, adding: %s", goal_md)
    add_frontmatter(goal_md, status)


def update_yaml_frontmatter(yaml_text: str, updates: dict[str, Any]) -> str:
    """Update YAML frontmatter with new values (IG-155).

    Args:
        yaml_text: Original YAML text
        updates: Dict of key-value updates

    Returns:
        Updated YAML text
    """
    lines = yaml_text.split("\n")
    updated_lines = []

    # Track which keys were updated
    updated_keys = set()

    for line in lines:
        if ":" in line:
            key = line.split(":", 1)[0].strip()
            if key in updates:
                # Update existing key
                value = updates[key]
                if value is None:
                    updated_lines.append(f"{key}: null")
                elif isinstance(value, str):
                    updated_lines.append(f"{key}: {value}")
                elif isinstance(value, list):
                    updated_lines.append(f"{key}: [{', '.join(value)}]")
                else:
                    updated_lines.append(f"{key}: {value}")
                updated_keys.add(key)
            else:
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    # Add new keys not in original
    for key, value in updates.items():
        if key not in updated_keys:
            if value is None:
                updated_lines.append(f"{key}: null")
            elif isinstance(value, str):
                updated_lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                updated_lines.append(f"{key}: [{', '.join(value)}]")
            else:
                updated_lines.append(f"{key}: {value}")

    return "\n".join(updated_lines)


def add_frontmatter(goal_md: Path, status: str) -> None:
    """Add frontmatter to GOAL.md without one (IG-155).

    Args:
        goal_md: Path to GOAL.md
        status: Initial status
    """
    content = goal_md.read_text()
    now = datetime.now(UTC).isoformat()

    frontmatter = f"---\nid: {goal_md.parent.name}\nstatus: {status}\ncreated_at: {now}\nupdated_at: {now}\n---\n"

    updated_content = frontmatter + content
    goal_md.write_text(updated_content)


def update_progress_section(
    goal_md: Path,
    progress_items: list[str],
    completed_items: list[str],
) -> None:
    """Update Progress section in GOAL.md (IG-155).

    Args:
        goal_md: Path to GOAL.md
        progress_items: List of progress item descriptions
        completed_items: List of completed item descriptions
    """
    content = goal_md.read_text()

    # Find or create Progress section
    if "## Progress" in content:
        # Replace existing Progress section
        lines = content.split("\n")
        new_lines = []
        in_progress_section = False

        for line in lines:
            if line.strip() == "## Progress":
                in_progress_section = True
                new_lines.append(line)
                new_lines.append("")
                # Add progress items
                for item in progress_items:
                    checked = "[x]" if item in completed_items else "[ ]"
                    new_lines.append(f"- {checked} {item}")
                new_lines.append("")
                new_lines.append(f"Last updated: {datetime.now(UTC).isoformat()}")
            elif in_progress_section and line.strip().startswith("##"):
                in_progress_section = False
                new_lines.append(line)
            elif not in_progress_section:
                new_lines.append(line)

        updated_content = "\n".join(new_lines)
    else:
        # Add new Progress section
        progress_section = "\n\n## Progress\n\n"
        for item in progress_items:
            checked = "[x]" if item in completed_items else "[ ]"
            progress_section += f"- {checked} {item}\n"
        progress_section += f"\nLast updated: {datetime.now(UTC).isoformat()}\n"

        updated_content = content + progress_section

    goal_md.write_text(updated_content)
    logger.info("Updated progress section in %s", goal_md)
