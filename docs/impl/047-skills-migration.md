# IG-047: Skills Migration from Nanobot to Soothe

## Overview

This implementation guide documents the migration of skills from the nanobot project (`/Users/chenxm/Workspace/nanobot/nanobot/skills`) to Soothe's builtin skills at `src/soothe/skills/`.

## Migration Summary

**Migrated**: 7 skills (weather, github, tmux, summarize, cron, clawhub, skill-creator)
**Skipped**: 1 skill (memory - replaced by Soothe's MemoryProtocol)

| Skill | Decision | Rationale |
|-------|----------|-----------|
| weather | Migrate | Zero dependencies (curl only), universally useful |
| github | Migrate | gh CLI is standard, useful for development workflows |
| tmux | Migrate | Session orchestration aligns with autonomous agents, has helper scripts |
| summarize | Migrate | Unique capability, complements research tools |
| cron | Migrate | Scheduling capability for reminders and recurring tasks |
| clawhub | Migrate | Access to public skill registry for discovering new skills |
| skill-creator | Migrate | Useful for users creating custom skills, has helper scripts |
| memory | Skip | Soothe uses MemoryProtocol instead of file-based MEMORY.md |

## Implementation

### Phase 1: Direct Migration (weather, github, summarize)

**Changes**:
1. Copied skill directories to `src/soothe/skills/`
2. Removed `homepage` field from frontmatter (not standard in Soothe)
3. Kept `metadata` with `emoji`, `requires.bins`, `install`
4. Updated path references in `summarize` skill: `~/.summarize/config.json` → `~/.soothe/summarize/config.json`

**Files created**:
- `src/soothe/skills/weather/SKILL.md`
- `src/soothe/skills/github/SKILL.md`
- `src/soothe/skills/summarize/SKILL.md`

### Phase 2: Migration with Scripts (tmux, skill-creator)

**tmux skill changes**:
1. Updated socket environment variable: `NANOBOT_TMUX_SOCKET_DIR` → `SOOTHE_TMUX_SOCKET_DIR`
2. Updated default socket path: `~/.nanobot/tmux-sockets/` → `~/.soothe/tmux-sockets/`
3. Updated script references from `{baseDir}/scripts/` to relative `scripts/`
4. Copied helper scripts and made them executable

**Files created**:
- `src/soothe/skills/tmux/SKILL.md`
- `src/soothe/skills/tmux/scripts/find-sessions.sh`
- `src/soothe/skills/tmux/scripts/wait-for-text.sh`

**skill-creator changes**:
1. Updated path references: `~/.nanobot/workspace/skills/` → `~/.soothe/skills/`
2. Updated skill discovery documentation for Soothe
3. Copied all scripts (init_skill.py, package_skill.py, quick_validate.py)

**Files created**:
- `src/soothe/skills/skill-creator/SKILL.md`
- `src/soothe/skills/skill-creator/scripts/init_skill.py`
- `src/soothe/skills/skill-creator/scripts/package_skill.py`
- `src/soothe/skills/skill-creator/scripts/quick_validate.py`

### Phase 3: Additional Skills (cron, clawhub)

**cron skill**: Migrated with minimal changes - updated documentation for Soothe context.
**clawhub skill**: Updated paths from `~/.nanobot/workspace` to `~/.soothe` for skill installation.

**Files created**:
- `src/soothe/skills/cron/SKILL.md`
- `src/soothe/skills/clawhub/SKILL.md`

### Phase 4: Documentation

Created comprehensive documentation for the skills directory.

**Files created**:
- `src/soothe/skills/README.md`

## File Structure

```
src/soothe/skills/
├── __init__.py
├── README.md (new)
├── create-subagent/
│   └── SKILL.md
├── weather/
│   └── SKILL.md
├── github/
│   └── SKILL.md
├── tmux/
│   ├── SKILL.md
│   └── scripts/
│       ├── find-sessions.sh
│       └── wait-for-text.sh
├── summarize/
│   └── SKILL.md
├── cron/
│   └── SKILL.md
├── clawhub/
│   └── SKILL.md
└── skill-creator/
    ├── SKILL.md
    └── scripts/
        ├── init_skill.py
        ├── package_skill.py
        └── quick_validate.py
```

## Key Differences from Nanobot

### Path Updates

| Nanobot | Soothe |
|---------|--------|
| `~/.nanobot/` | `~/.soothe/` |
| `NANOBOT_TMUX_SOCKET_DIR` | `SOOTHE_TMUX_SOCKET_DIR` |
| `~/.nanobot/workspace/skills/` | `~/.soothe/skills/` |

### Memory System

**Nanobot**: File-based (MEMORY.md for facts, HISTORY.md for events)
**Soothe**: Protocol-based (MemoryProtocol for cross-thread, ContextProtocol for within-thread)

The memory skill was not migrated because Soothe uses a different memory architecture via MemoryProtocol and ContextProtocol.

### Skill Discovery

Both use deepagents' SkillsMiddleware, but Soothe provides `get_built_in_skills_paths()` for builtin skill discovery.

## Verification

### Skill Count
- Expected: 8 skills (create-subagent + 7 migrated)
- Found: 8 skills ✓

### File Structure
- All SKILL.md files present ✓
- Scripts executable ✓
- Proper frontmatter format ✓

### Frontmatter Validation
All skills have required fields:
- `name`: Matches directory name ✓
- `description`: Clear triggering guidance ✓
- `metadata` (optional): Properly formatted ✓

## Testing

### Manual Tests

**Weather skill**:
```bash
# Should trigger on: "What's the weather in Seattle?"
# Expected: Uses curl to query wttr.in
```

**GitHub skill**:
```bash
# Should trigger on: "Create a PR for my changes"
# Expected: Uses gh CLI commands
```

**tmux skill**:
```bash
# Should trigger on: "Start a tmux session for parallel work"
# Expected: Provides socket convention and helper scripts
```

**summarize skill**:
```bash
# Should trigger on: "Summarize this YouTube video"
# Expected: Uses summarize CLI with --youtube flag
```

**memory-management skill**:
```bash
# Should trigger on: "How do I save facts across sessions?"
# Expected: Teaches MemoryProtocol usage
```

**skill-creator skill**:
```bash
# Should trigger on: "Create a new skill for my workflow"
# Expected: Guides through skill creation process
```

### Script Tests

**tmux scripts**:
```bash
# Find sessions
src/soothe/skills/tmux/scripts/find-sessions.sh --help

# Wait for text
src/soothe/skills/tmux/scripts/wait-for-text.sh --help
```

**skill-creator scripts**:
```bash
# Initialize skill
python3 src/soothe/skills/skill-creator/scripts/init_skill.py test-skill --path /tmp

# Validate skill
python3 src/soothe/skills/skill-creator/scripts/quick_validate.py /tmp/test-skill

# Package skill
python3 src/soothe/skills/skill-creator/scripts/package_skill.py /tmp/test-skill
```

## Integration with Soothe

### Automatic Discovery

Builtin skills are discovered automatically by `get_built_in_skills_paths()` in `src/soothe/skills/__init__.py`:

```python
def get_built_in_skills_paths() -> list[str]:
    """Get filesystem paths to all built-in skills."""
    # Uses importlib.resources to find skills whether installed from wheel or running from source
    # Scans src/soothe/skills/ for subdirectories containing SKILL.md
```

### Configuration

Users can add custom skills via `SootheConfig`:

```python
from soothe.config import SootheConfig

config = SootheConfig(
    skills=["~/.soothe/skills/", "/path/to/custom/skills/"]
)
```

### Loading Order

Skills are merged in order (last wins):
1. Built-in skills from `get_built_in_skills_paths()`
2. User-configured skills from `SootheConfig.skills`

## Future Improvements

1. **Testing**: Add unit tests for skill discovery and loading
2. **Validation**: Run skill-creator's quick_validate.py in CI
3. **Documentation**: Add skill usage examples to user guide
4. **Integration**: Test skills with actual Soothe agent execution

## References

- [RFC-0001](../specs/RFC-0001.md) - System Conceptual Design
- [RFC-0002](../specs/RFC-0002.md) - Core Modules Architecture
- Agent Skills Specification: https://agentskills.io
- deepagents SkillsMiddleware: `thirdparty/deepagents/libs/deepagents/deepagents/middleware/skills.py`