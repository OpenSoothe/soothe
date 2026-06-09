"""Goal discovery from autopilot directory (RFC-200 §339, IG-155)."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GoalDefinition(BaseModel):
    """Parsed goal definition from markdown file (RFC-200, IG-155).

    Attributes:
        id: Goal identifier (from frontmatter or generated)
        description: Goal text (from markdown body)
        priority: Scheduling priority (0-100)
        depends_on: Prerequisite goal IDs
        status: Current status (pending, active, completed, failed)
        error: Error message (if failed)
        created_at: Creation timestamp
        updated_at: Last update timestamp
        source_file: Path to GOAL.md file
    """

    id: str
    description: str
    priority: int = Field(default=50, ge=0, le=100)
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source_file: Path | None = None


def discover_goals(autopilot_dir: Path) -> list[GoalDefinition]:
    """Discover goals from autopilot directory (RFC-200 §339, IG-155).

    Scans in priority order:
    1. autopilot/GOAL.md (single goal mode)
    2. autopilot/GOALS.md (batch mode)
    3. autopilot/goals/*/GOAL.md (per-goal files)

    Args:
        autopilot_dir: Path to $SOOTHE_HOME/autopilot/

    Returns:
        List of GoalDefinition objects

    Raises:
        ValueError: If autopilot_dir does not exist
    """
    if not autopilot_dir.exists():
        raise ValueError(f"Autopilot directory does not exist: {autopilot_dir}")

    goals = []

    # Priority 1: Single goal mode
    goal_md = autopilot_dir / "GOAL.md"
    if goal_md.exists():
        goal = parse_goal_file(goal_md)
        goals.append(goal)
        logger.info("Discovered single goal from GOAL.md: %s", goal.id)
        return goals  # Single mode, skip other discovery

    # Priority 2: Batch mode
    goals_md = autopilot_dir / "GOALS.md"
    if goals_md.exists():
        batch_goals = parse_goals_batch(goals_md)
        goals.extend(batch_goals)
        logger.info("Discovered %d goals from GOALS.md", len(batch_goals))

    # Priority 3: Subdirectory scanning
    goals_subdir = autopilot_dir / "goals"
    if goals_subdir.exists() and goals_subdir.is_dir():
        for subdir in sorted(goals_subdir.iterdir()):
            if subdir.is_dir():
                goal_md = subdir / "GOAL.md"
                if goal_md.exists():
                    goal = parse_goal_file(goal_md)
                    goals.append(goal)
                    logger.info("Discovered goal from goals/%s/GOAL.md: %s", subdir.name, goal.id)

    if not goals:
        logger.warning("No goals discovered from autopilot directory: %s", autopilot_dir)

    return goals


def parse_goal_file(goal_md: Path) -> GoalDefinition:
    """Parse single GOAL.md file with YAML frontmatter (IG-155).

    Format:
        ---
        id: goal-id
        priority: 80
        depends_on: []
        ---

        # Goal Title

        Goal description text...

    Args:
        goal_md: Path to GOAL.md file

    Returns:
        GoalDefinition with parsed metadata and description

    Raises:
        ValueError: If file format is invalid
    """
    content = goal_md.read_text()

    # Split frontmatter and body
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter_yaml = parts[1].strip()
            body = parts[2].strip()

            # Parse YAML frontmatter
            metadata = parse_yaml_frontmatter(frontmatter_yaml)

            # Extract description from body (first paragraph after title)
            description = extract_goal_description(body)

            # Generate ID if not provided
            goal_id = metadata.get("id") or generate_goal_id(goal_md)

            return GoalDefinition(
                id=goal_id,
                description=description,
                priority=metadata.get("priority", 50),
                depends_on=metadata.get("depends_on", []),
                status=metadata.get("status", "pending"),
                error=metadata.get("error"),
                created_at=parse_datetime(metadata.get("created_at")),
                updated_at=parse_datetime(metadata.get("updated_at")),
                source_file=goal_md,
            )

    # No frontmatter: generate from filename
    logger.warning("GOAL.md has no frontmatter: %s", goal_md)
    description = goal_md.read_text().strip().split("\n\n")[0]
    return GoalDefinition(
        id=generate_goal_id(goal_md),
        description=description,
        source_file=goal_md,
    )


def parse_goals_batch(goals_md: Path) -> list[GoalDefinition]:
    """Parse GOALS.md batch file with multiple goals (IG-155).

    Format:
        # Project Goals

        ## Goal: Goal Title
        - id: goal-id
        - priority: 90
        - depends_on: []

        Goal description text...

    Args:
        goals_md: Path to GOALS.md file

    Returns:
        List of GoalDefinition objects
    """
    content = goals_md.read_text()
    goals = []

    # Split by "## Goal:" sections
    goal_sections = re.split(r"## Goal: ", content)

    for section in goal_sections[1:]:  # Skip first (before any goal)
        # Parse goal section
        lines = section.split("\n")

        # Extract title (first line)
        title = lines[0].strip()

        # Extract metadata (lines starting with -)
        metadata_lines = [line.strip() for line in lines[1:10] if line.strip().startswith("-")]
        metadata = parse_list_metadata(metadata_lines)

        # Extract description (text after metadata)
        description_lines = []
        for line in lines[10:]:
            if line.strip().startswith("##"):
                break  # Next goal section
            description_lines.append(line)

        description = title + "\n" + "\n".join(description_lines).strip()

        goals.append(
            GoalDefinition(
                id=metadata.get("id", generate_goal_id_from_title(title)),
                description=description,
                priority=metadata.get("priority", 50),
                depends_on=parse_depends_on(metadata.get("depends_on", "")),
                source_file=goals_md,
            )
        )

    return goals


def parse_yaml_frontmatter(yaml_text: str) -> dict[str, Any]:
    """Parse YAML frontmatter into dict (simple parser, IG-155).

    Args:
        yaml_text: YAML text from frontmatter

    Returns:
        Dict of key-value pairs
    """
    # Simple YAML parser (avoid yaml library dependency)
    metadata = {}
    for line in yaml_text.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            # Parse value types
            if value.startswith("["):
                # List: [item1, item2]
                items = value[1:-1].split(",")
                metadata[key] = [i.strip() for i in items if i.strip()]
            elif value.isdigit():
                metadata[key] = int(value)
            elif value in ("true", "false"):
                metadata[key] = value == "true"
            elif value == "null":
                metadata[key] = None
            else:
                metadata[key] = value

    return metadata


def parse_list_metadata(metadata_lines: list[str]) -> dict[str, Any]:
    """Parse list-style metadata from GOALS.md sections (IG-155).

    Args:
        metadata_lines: Lines like "- id: goal-id"

    Returns:
        Dict of key-value pairs
    """
    metadata = {}
    for line in metadata_lines:
        if line.startswith("-") and ":" in line:
            key, value = line[1:].split(":", 1)
            key = key.strip()
            value = value.strip()

            if value.isdigit():
                metadata[key] = int(value)
            elif value.startswith("["):
                items = value[1:-1].split(",")
                metadata[key] = [i.strip() for i in items if i.strip()]
            else:
                metadata[key] = value

    return metadata


def extract_goal_description(body: str) -> str:
    """Extract goal description from markdown body (IG-155).

    Takes first paragraph after title.

    Args:
        body: Markdown body text

    Returns:
        Goal description text
    """
    # Remove title (first # heading)
    lines = body.split("\n")
    description_lines = []

    # Skip title and blank lines after it
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#"):
            start_idx = i + 1
            break

    # Collect description lines until next section
    for line in lines[start_idx:]:
        if line.strip().startswith("#") or line.strip().startswith("##"):
            break
        if line.strip():
            description_lines.append(line)

    return "\n".join(description_lines).strip()


def generate_goal_id(goal_md: Path) -> str:
    """Generate goal ID from file path (IG-155).

    Args:
        goal_md: Path to GOAL.md

    Returns:
        8-char hex ID based on directory name
    """
    # Use parent directory name as ID
    parent_name = goal_md.parent.name
    if parent_name and parent_name != "autopilot":
        # Sanitize: lowercase, alphanumeric only
        sanitized = re.sub(r"[^a-zA-Z0-9]", "", parent_name.lower())
        return sanitized[:8] if sanitized else hashlib.md5(str(goal_md).encode()).hexdigest()[:8]

    # Fallback: generate random ID
    return hashlib.md5(str(goal_md).encode()).hexdigest()[:8]


def generate_goal_id_from_title(title: str) -> str:
    """Generate goal ID from goal title (IG-155).

    Args:
        title: Goal title text

    Returns:
        8-char hex ID
    """
    return hashlib.md5(title.encode()).hexdigest()[:8]


def parse_depends_on(depends_str: str) -> list[str]:
    """Parse depends_on string from GOALS.md (IG-155).

    Args:
        depends_str: String like "pipeline, report" or "[pipeline, report]"

    Returns:
        List of goal IDs
    """
    if not depends_str:
        return []

    # Remove brackets if present
    depends_str = depends_str.strip("[]")

    # Split by comma
    return [d.strip() for d in depends_str.split(",") if d.strip()]


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO datetime string (IG-155).

    Args:
        dt_str: ISO datetime string

    Returns:
        datetime object or None
    """
    if not dt_str:
        return None

    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Invalid datetime: %s", dt_str)
        return None
