# IG-155: Autopilot Goal Discovery Implementation

**ID**: IG-155
**Title**: Autopilot Goal Discovery from File System
**Status**: Draft
**Created**: 2026-04-12
**RFC References**: RFC-200 §339-505 (Autopilot Working Directory)
**Priority**: P1 (High - Missing Feature)
**Estimated Effort**: 4-5 days

---

## Abstract

This guide implements the autopilot working directory system, enabling goal discovery from `$SOOTHE_HOME/autopilot/` markdown files. Users can define goals in `GOAL.md` and `GOALS.md` files with YAML frontmatter, and Soothe will automatically discover, load, and track goal progress through file-based status updates. This feature enables persistent goal management for long-running autonomous agents.

---

## Problem Statement

### Current Gap

**RFC-200 specifies**:
- `$SOOTHE_HOME/autopilot/` directory structure
- Goal discovery algorithm scanning GOAL.md, GOALS.md, subdirectories
- YAML frontmatter parsing for goal metadata (id, priority, depends_on)
- Goal status tracking in markdown files
- Optional file watching for live updates

**Current implementation**: ❌ **NONE**

Goals are only created programmatically via:
```python
goal = await self._goal_engine.create_goal(
    description=user_input,
    priority=80,
    parent_id=None,
    depends_on=[],
)
```

### Impact

1. **No File-Based Goals**: Cannot define goals in persistent files
2. **No Autopilot Mode**: Cannot run unattended from predefined goal files
3. **No Progress Tracking**: Cannot update goal status back to files
4. **No Discovery Mechanism**: No scanning for goal definitions
5. **Reduced Autonomy**: Goals must be created through API/CLI only

---

## Solution Design

### Directory Structure

```
$SOOTHE_HOME/
└── autopilot/
    ├── GOAL.md              # Single goal definition (autopilot root)
    ├── GOALS.md             # Multiple goals definition (autopilot root)
    └── goals/               # Per-goal subdirectories
        ├── data-pipeline/
        │   ├── GOAL.md      # Goal definition
        │   ├── context.md   # Supporting context files
        │   └── data/        # Goal-specific data
        └── report-generation/
            ├── GOAL.md
            └── templates/
```

### Goal File Format

#### Single Goal (`GOAL.md`)

```markdown
---
id: data-pipeline
priority: 80
depends_on: []
status: pending
error: null
created_at: 2026-04-12T10:30:00Z
updated_at: 2026-04-12T10:30:00Z
---

# Feature: Data Processing Pipeline

Implement a robust data processing pipeline with validation and error handling.

## Success Criteria
- Data is validated before processing
- Errors are properly handled and logged
- Pipeline produces correct output files

## Progress

- [x] Design pipeline architecture
- [x] Implement data validation
- [ ] Add error handling
- [ ] Write tests

Last updated: 2026-04-12T14:30:00Z
```

#### Multiple Goals (`GOALS.md`)

```markdown
# Project Goals

## Goal: Data Pipeline
- id: pipeline
- priority: 90
- depends_on: []

Implement the data processing pipeline.

## Goal: Report Generation
- id: report
- priority: 70
- depends_on: [pipeline]

Build the report generation from processed data.

## Goal: Testing
- id: testing
- priority: 60
- depends_on: [pipeline, report]

Write comprehensive tests for the system.
```

### Discovery Algorithm

**Priority Order**:
1. **Autopilot GOAL.md**: Single goal mode (highest priority)
2. **Autopilot GOALS.md**: Batch mode (multiple goals)
3. **Goals subdirectory**: `autopilot/goals/*/GOAL.md` (per-goal files)

**Implementation**:
```python
def discover_goals(autopilot_dir: Path) -> list[GoalDefinition]:
    """Discover goals from autopilot directory (RFC-200 §339)."""
    goals = []
    
    # Priority 1: Single goal mode
    if (autopilot_dir / "GOAL.md").exists():
        goal = parse_goal_file(autopilot_dir / "GOAL.md")
        goals.append(goal)
        logger.info("Discovered single goal from GOAL.md: %s", goal.id)
        return goals  # Single mode, skip other discovery
    
    # Priority 2: Batch mode
    if (autopilot_dir / "GOALS.md").exists():
        batch_goals = parse_goals_batch(autopilot_dir / "GOALS.md")
        goals.extend(batch_goals)
        logger.info("Discovered %d goals from GOALS.md", len(batch_goals))
    
    # Priority 3: Subdirectory scanning
    goals_subdir = autopilot_dir / "goals"
    if goals_subdir.exists() and goals_subdir.is_dir():
        for subdir in sorted(goals_subdir.iterdir()):
            if subdir.is_dir() and (subdir / "GOAL.md").exists():
                goal = parse_goal_file(subdir / "GOAL.md")
                goals.append(goal)
                logger.info("Discovered goal from goals/%s/GOAL.md: %s", subdir.name, goal.id)
    
    return goals
```

---

## Implementation Steps

### Step 1: Create Goal Discovery Module

**File**: `src/soothe/cognition/goal_engine/discovery.py` (NEW)

```python
"""Goal discovery from autopilot directory (RFC-200 §339)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GoalDefinition(BaseModel):
    """Parsed goal definition from markdown file.
    
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
    """Discover goals from autopilot directory (RFC-200 §339).
    
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
    """Parse single GOAL.md file with YAML frontmatter.
    
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
    """Parse GOALS.md batch file with multiple goals.
    
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
        metadata_lines = [l.strip() for l in lines[1:10] if l.strip().startswith("-")]
        metadata = parse_list_metadata(metadata_lines)
        
        # Extract description (text after metadata)
        description_lines = []
        for line in lines[10:]:
            if line.strip().startswith("##"):
                break  # Next goal section
            description_lines.append(line)
        
        description = title + "\n" + "\n".join(description_lines).strip()
        
        goals.append(GoalDefinition(
            id=metadata.get("id", generate_goal_id_from_title(title)),
            description=description,
            priority=metadata.get("priority", 50),
            depends_on=parse_depends_on(metadata.get("depends_on", "")),
            source_file=goals_md,
        ))
    
    return goals


def parse_yaml_frontmatter(yaml_text: str) -> dict[str, Any]:
    """Parse YAML frontmatter into dict (simple parser).
    
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
    """Parse list-style metadata from GOALS.md sections.
    
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
    """Extract goal description from markdown body.
    
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
    """Generate goal ID from file path.
    
    Args:
        goal_md: Path to GOAL.md
    
    Returns:
        8-char hex ID based on directory name
    """
    # Use parent directory name as ID
    parent_name = goal_md.parent.name
    if parent_name and parent_name != "autopilot":
        return parent_name[:8]
    
    # Fallback: generate random ID
    import hashlib
    hash_input = str(goal_md)
    return hashlib.md5(hash_input.encode()).hexdigest()[:8]


def generate_goal_id_from_title(title: str) -> str:
    """Generate goal ID from goal title.
    
    Args:
        title: Goal title text
    
    Returns:
        8-char hex ID
    """
    import hashlib
    return hashlib.md5(title.encode()).hexdigest()[:8]


def parse_depends_on(depends_str: str) -> list[str]:
    """Parse depends_on string from GOALS.md.
    
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
    """Parse ISO datetime string.
    
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
```

### Step 2: Create Goal File Writer

**File**: `src/soothe/cognition/goal_engine/writer.py` (NEW)

```python
"""Goal status tracking in markdown files (RFC-200 §339)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soothe.cognition.goal_engine.discovery import GoalDefinition

logger = logging.getLogger(__name__)


def update_goal_status(
    goal_md: Path,
    status: str,
    error: str | None = None,
) -> None:
    """Update goal status in GOAL.md frontmatter.
    
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
    """Update YAML frontmatter with new values.
    
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
    """Add frontmatter to GOAL.md without one.
    
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
    """Update Progress section in GOAL.md.
    
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
```

### Step 3: Integrate Discovery into Runner

**File**: `src/soothe/core/runner/_runner_autonomous.py`

**Add initialization**:
```python
async def initialize_autopilot(self, soothe_home: Path) -> None:
    """Initialize autopilot mode from goal files (RFC-200 §339).
    
    Args:
        soothe_home: Path to $SOOTHE_HOME
    """
    from soothe.cognition.goal_engine.discovery import discover_goals
    from soothe.config import SOOTHE_HOME
    
    autopilot_dir = soothe_home / "autopilot"
    
    # Ensure directory structure exists
    autopilot_dir.mkdir(parents=True, exist_ok=True)
    (autopilot_dir / "goals").mkdir(exist_ok=True)
    
    # Discover goals
    goal_definitions = discover_goals(autopilot_dir)
    
    if not goal_definitions:
        logger.warning("No goals discovered from autopilot directory")
        return
    
    # Create goals in GoalEngine
    for goal_def in goal_definitions:
        try:
            await self._goal_engine.create_goal(
                description=goal_def.description,
                priority=goal_def.priority,
                goal_id=goal_def.id,
                depends_on=goal_def.depends_on,
                source_file=str(goal_def.source_file) if goal_def.source_file else None,
            )
            logger.info("Loaded goal %s from file", goal_def.id)
        except Exception:
            logger.exception("Failed to create goal %s", goal_def.id)
```

**Modify autonomous runner entry**:
```python
async def _run_autonomous(
    self,
    user_input: str,
    *,
    thread_id: str | None = None,
    workspace: str | None = None,
    max_iterations: int = 10,
) -> AsyncGenerator[StreamChunk]:
    """Autonomous iteration loop with DAG-based goal scheduling."""
    
    # ... existing code ...
    
    # NEW: Check if autopilot mode (no user input, discover from files)
    if not user_input or user_input.strip() == "":
        logger.info("Autopilot mode: discovering goals from files")
        await self.initialize_autopilot(SOOTHE_HOME)
        
        # Check if goals were discovered
        if not self._goal_engine or not self._goal_engine.list_goals():
            yield _custom(ErrorEvent(code="NO_GOALS", message="No goals found in autopilot directory").to_dict())
            return
    else:
        # User provided goal input
        goal = await self._goal_engine.create_goal(user_input, priority=80)
        # ... existing goal creation logic ...
```

### Step 4: Update Goal Status on Completion

**File**: `src/soothe/cognition/goal_engine/engine.py`

**Add source_file tracking**:
```python
class Goal(BaseModel):
    # ... existing fields ...
    source_file: str | None = None  # ✅ NEW: Track GOAL.md path
```

**Update completion/failure methods**:
```python
async def complete_goal(self, goal_id: str) -> None:
    """Mark goal as completed."""
    goal = self._goals.get(goal_id)
    if goal:
        goal.status = "completed"
        goal.updated_at = datetime.now(UTC)
        
        # ✅ NEW: Update source file
        if goal.source_file:
            from soothe.cognition.goal_engine.writer import update_goal_status
            update_goal_status(Path(goal.source_file), "completed")
        
        logger.info("Goal %s completed", goal_id)

async def fail_goal(self, goal_id: str, error: str, allow_retry: bool = True) -> None:
    """Mark goal as failed."""
    goal = self._goals.get(goal_id)
    if goal:
        goal.status = "failed"
        goal.error = error
        goal.updated_at = datetime.now(UTC)
        
        # ✅ NEW: Update source file
        if goal.source_file:
            from soothe.cognition.goal_engine.writer import update_goal_status
            update_goal_status(Path(goal.source_file), "failed", error=error)
        
        logger.warning("Goal %s failed: %s", goal_id, error)
```

### Step 5: Add CLI Integration

**File**: `src/soothe/cli/main.py`

**Add autopilot command**:
```python
@app.command("autopilot")
def autopilot_command(
    goal_file: str | None = None,
    max_iterations: int = 10,
    no_watch: bool = False,
) -> None:
    """Run autonomous agent from goal files (RFC-200).
    
    Args:
        goal_file: Path to specific GOAL.md file
        max_iterations: Max autonomous iterations
        no_watch: Disable file watching
    """
    from soothe.config import SOOTHE_HOME
    from soothe.core.runner import SootheRunner
    
    config = SootheConfig.from_env()
    runner = SootheRunner(config)
    
    # Initialize autopilot directory
    autopilot_dir = SOOTHE_HOME / "autopilot"
    
    if goal_file:
        # Specific goal file
        goal_md = Path(goal_file)
        if not goal_md.exists():
            console.print(f"[red]Goal file not found: {goal_file}[/red]")
            return
        
        # Copy to autopilot directory
        goal_dir = autopilot_dir / "goals" / goal_md.parent.name
        goal_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(goal_md, goal_dir / "GOAL.md")
        
        console.print(f"[green]Loaded goal from: {goal_file}[/green]")
    
    # Run autonomous loop with empty input (discover from files)
    asyncio.run(run_autonomous_loop(runner, "", max_iterations))


async def run_autonomous_loop(runner: SootheRunner, user_input: str, max_iterations: int) -> None:
    """Execute autonomous loop."""
    async for chunk in runner.astream(user_input, autonomous=True, max_iterations=max_iterations):
        # Display events
        # ... existing TUI display logic ...
```

### Step 6: Add File Watching (Optional)

**File**: `src/soothe/cognition/goal_engine/watcher.py` (NEW)

```python
"""Goal file watcher for long-running autopilot sessions (RFC-200)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from soothe.cognition.goal_engine.discovery import parse_goal_file
from soothe.cognition.goal_engine.engine import GoalEngine

logger = logging.getLogger(__name__)


class GoalFileWatcher(FileSystemEventHandler):
    """Watch for changes to goal files and sync with GoalEngine."""
    
    def __init__(self, goal_engine: GoalEngine) -> None:
        """Initialize watcher.
        
        Args:
            goal_engine: GoalEngine to sync with
        """
        self.goal_engine = goal_engine
        self.observer = Observer()
    
    def start(self, autopilot_dir: Path) -> None:
        """Start watching autopilot directory.
        
        Args:
            autopilot_dir: Directory to watch
        """
        self.observer.schedule(self, str(autopilot_dir), recursive=True)
        self.observer.start()
        logger.info("Started goal file watcher on %s", autopilot_dir)
    
    def stop(self) -> None:
        """Stop watching."""
        self.observer.stop()
        self.observer.join()
        logger.info("Stopped goal file watcher")
    
    def on_modified(self, event: Any) -> None:
        """Handle file modification.
        
        Args:
            event: FileSystemEvent
        """
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        if path.name == "GOAL.md":
            logger.info("Goal file modified: %s", path)
            self._sync_goal_file(path)
    
    def on_created(self, event: Any) -> None:
        """Handle file creation.
        
        Args:
            event: FileSystemEvent
        """
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        if path.name == "GOAL.md":
            logger.info("New goal file created: %s", path)
            self._sync_goal_file(path)
    
    def _sync_goal_file(self, goal_md: Path) -> None:
        """Sync GOAL.md with GoalEngine.
        
        Args:
            goal_md: Path to modified GOAL.md
        """
        try:
            goal_def = parse_goal_file(goal_md)
            
            existing = self.goal_engine.get_goal(goal_def.id)
            
            if not existing:
                # Create new goal
                asyncio.run(self.goal_engine.create_goal(
                    description=goal_def.description,
                    priority=goal_def.priority,
                    goal_id=goal_def.id,
                    depends_on=goal_def.depends_on,
                    source_file=str(goal_md),
                ))
                logger.info("Created new goal %s from file change", goal_def.id)
            else:
                # Update existing goal
                existing.description = goal_def.description
                existing.priority = goal_def.priority
                existing.depends_on = goal_def.depends_on
                existing.updated_at = goal_def.updated_at
                logger.info("Updated goal %s from file change", goal_def.id)
        
        except Exception:
            logger.exception("Failed to sync goal file: %s", goal_md)
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/cognition/goal_engine/test_discovery.py`

```python
def test_parse_goal_file_with_frontmatter():
    """Test parsing GOAL.md with complete frontmatter."""
    goal_md = Path("test_fixtures/goal_with_frontmatter.md")
    goal = parse_goal_file(goal_md)
    
    assert goal.id == "data-pipeline"
    assert goal.priority == 80
    assert goal.depends_on == []
    assert goal.status == "pending"
    assert goal.description.startswith("Implement")


def test_parse_goal_file_no_frontmatter():
    """Test parsing GOAL.md without frontmatter."""
    goal_md = Path("test_fixtures/goal_no_frontmatter.md")
    goal = parse_goal_file(goal_md)
    
    assert goal.id  # Generated
    assert goal.description


def test_parse_goals_batch():
    """Test parsing GOALS.md with multiple goals."""
    goals_md = Path("test_fixtures/goals_batch.md")
    goals = parse_goals_batch(goals_md)
    
    assert len(goals) == 3
    assert goals[0].id == "pipeline"
    assert goals[1].depends_on == ["pipeline"]


def test_discover_goals_priority():
    """Test discovery priority order."""
    autopilot_dir = Path("test_fixtures/autopilot_full")
    goals = discover_goals(autopilot_dir)
    
    # Single GOAL.md takes priority
    assert len(goals) == 1
    assert goals[0].id == "single-goal"


def test_discover_goals_subdirectory():
    """Test subdirectory scanning."""
    autopilot_dir = Path("test_fixtures/autopilot_subdirs")
    goals = discover_goals(autopilot_dir)
    
    # Should find goals/ subdirectory GOAL.md files
    assert len(goals) >= 2
```

### Integration Tests

```python
async def test_autopilot_initialization():
    """Test autopilot mode initialization from files."""
    # Setup test autopilot directory
    autopilot_dir = SOOTHE_HOME / "autopilot"
    (autopilot_dir / "goals" / "test-goal").mkdir(parents=True)
    (autopilot_dir / "goals" / "test-goal" / "GOAL.md").write_text(
        "---\nid: test-goal\npriority: 90\n---\n\n# Test Goal\nTest goal description"
    )
    
    config = SootheConfig()
    runner = SootheRunner(config)
    
    await runner.initialize_autopilot(SOOTHE_HOME)
    
    # Verify goal loaded
    goals = runner._goal_engine.list_goals()
    assert len(goals) == 1
    assert goals[0].id == "test-goal"


async def test_goal_status_update():
    """Test goal status tracking in files."""
    goal_md = Path("test_fixtures/goal.md")
    
    update_goal_status(goal_md, "completed")
    
    # Read updated file
    content = goal_md.read_text()
    assert "status: completed" in content
    assert "updated_at:" in content


async def test_full_autopilot_workflow():
    """Test complete autopilot workflow."""
    config = SootheConfig(autonomous={"enabled": True})
    runner = SootheRunner(config)
    
    # Initialize autopilot
    await runner.initialize_autopilot(SOOTHE_HOME)
    
    # Run autonomous loop
    chunks = []
    async for chunk in runner.astream("", autonomous=True, max_iterations=3):
        chunks.append(chunk)
    
    # Verify goals discovered
    assert any(c["type"] == "soothe.cognition.goal.created" for c in chunks)
    
    # Verify status updated in files
    goals = runner._goal_engine.list_goals(status="completed")
    for goal in goals:
        if goal.source_file:
            goal_md = Path(goal.source_file)
            content = goal_md.read_text()
            assert "status: completed" in content
```

---

## Migration Path

### Phase 1: Implement Core Discovery

1. Create `discovery.py` module with parsing logic
2. Create test fixtures with example GOAL.md files
3. Unit test parsing functions

### Phase 2: Integrate with GoalEngine

1. Add `source_file` field to Goal model
2. Add `initialize_autopilot()` to runner
3. Test goal creation from discovered definitions

### Phase 3: Add Status Tracking

1. Create `writer.py` module for file updates
2. Integrate status updates into GoalEngine completion/failure
3. Test file status synchronization

### Phase 4: CLI Integration

1. Add `autopilot` command to CLI
2. Add `--goal-file` option
3. Test end-to-end autopilot workflow

### Phase 5: Optional File Watching

1. Create `watcher.py` module with watchdog
2. Integrate watcher into long-running sessions
3. Add `--no-watch` option to disable

---

## Expected Outcomes

### Functional Benefits

1. **File-Based Goals**: Users can define goals in markdown files
2. **Autopilot Mode**: Run unattended from predefined goal files
3. **Progress Tracking**: Goal status visible in files
4. **Persistent Goals**: Goals survive across sessions
5. **Goal File Management**: Organize goals in directory structure

### User Experience

```bash
# Create goal file
$ mkdir -p ~/.soothe/autopilot/goals/data-pipeline
$ cat > ~/.soothe/autopilot/goals/data-pipeline/GOAL.md << 'EOF'
---
id: data-pipeline
priority: 90
depends_on: []
---

# Feature: Data Processing Pipeline

Implement robust data processing with validation.
EOF

# Run autopilot
$ soothe autopilot

# Monitor progress
$ cat ~/.soothe/autopilot/goals/data-pipeline/GOAL.md
---
id: data-pipeline
status: active
updated_at: 2026-04-12T14:30:00Z
---

## Progress
- [x] Design pipeline architecture
- [ ] Implement data validation
- [ ] Write tests
```

---

## Validation Checklist

After implementation:

- [ ] discovery.py parses GOAL.md with frontmatter
- [ ] discovery.py parses GOALS.md batch format
- [ ] discovery.py scans subdirectories
- [ ] Priority order: GOAL.md > GOALS.md > subdirs
- [ ] GoalEngine.create_goal() accepts source_file
- [ ] Runner.initialize_autopilot() loads goals from files
- [ ] GoalEngine.complete_goal() updates file status
- [ ] GoalEngine.fail_goal() updates file status + error
- [ ] CLI `soothe autopilot` command works
- [ ] CLI `--goal-file` option works
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] File watching (optional) works

---

## References

- RFC-200 §339-505: Autopilot Working Directory
- RFC-200 §Goal File Format: Frontmatter specification
- IG-154: Layer 3 AgentLoop Integration (prerequisite)
- `src/soothe/cognition/goal_engine/engine.py`
- `src/soothe/cli/main.py`

---

## Estimated Timeline

- **Day 1**: Implement discovery.py with parsing
- **Day 2**: Integrate with GoalEngine, add source_file
- **Day 3**: Implement writer.py for status tracking
- **Day 4**: CLI integration and testing
- **Day 5**: Optional file watching, final validation

**Total**: 4-5 days

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| YAML parsing complexity | Medium | Use simple parser, avoid yaml library |
| File corruption on write | High | Atomic writes: write to tmp, rename |
| Concurrent file access | Medium | File locks, safe read/write patterns |
| Frontmatter validation | Medium | Schema validation, fallback to defaults |
| Discovery performance | Low | Lazy discovery, cache parsed goals |

---

**Next**: Proceed to IG-156 (RFC Status Updates)