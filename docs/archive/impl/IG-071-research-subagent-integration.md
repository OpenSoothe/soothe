# IG-071: Research Subagent Slash Command Integration

**Date**: 2026-03-27
**Status**: ✅ Completed
**Impact**: User-facing feature integration

## Summary

Fixed missing integration points for the Research subagent slash command (`/research`). The research subagent was fully implemented following RFC-601 but was not accessible via slash commands due to missing registration in three key locations.

## Problem

Users could not use `/research <query>` slash command despite the research subagent being fully implemented:

```bash
# This didn't work before
> /research meaning of balabalaxmx
# Treated as regular input, no routing to research subagent
```

## Root Cause

The research subagent implementation (RFC-601) was complete but integration was partial:
- ✅ Plugin class defined with `@plugin` and `@subagent` decorators
- ✅ Factory function `create_research_subagent()` implemented
- ✅ Custom events registered
- ❌ **Missing from `SUBAGENT_FACTORIES`** (resolver)
- ❌ **Missing from `SUBAGENT_DISPLAY_NAMES`** (CLI commands)
- ❌ **Missing from `SLASH_COMMANDS`** (TUI help)

## Changes Made

### 1. Core Resolver (`src/soothe/core/resolver/_resolver_tools.py`)

**Added research to subagent factories**:

```python
def _get_subagent_factories() -> dict[str, Callable[..., SubAgent | CompiledSubAgent]]:
    from soothe.subagents.browser import create_browser_subagent
    from soothe.subagents.claude import create_claude_subagent
    from soothe.subagents.research import create_research_subagent  # ← NEW
    from soothe.subagents.skillify import create_skillify_subagent
    from soothe.subagents.weaver import create_weaver_subagent

    return {
        "browser": create_browser_subagent,
        "claude": create_claude_subagent,
        "research": create_research_subagent,  # ← NEW
        "skillify": create_skillify_subagent,
        "weaver": create_weaver_subagent,
    }
```

**Impact**: Agent factory can now resolve research subagent when building the agent.

### 2. Subagent Display Names (`src/soothe/ux/cli/commands/subagent_names.py`)

**Added research to display names**:

```python
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "browser": "Browser",
    "claude": "Claude",
    "research": "Research",  # ← NEW
    "skillify": "Skillify",
    "weaver": "Weaver",
}
```

**Impact**:
- `parse_subagent_from_input()` now recognizes `/research` commands
- Works both as **prefix** (`/research query`) and **inline** (`Can you /research this`)
- TUI routing now functions correctly

### 3. Slash Commands (`src/soothe/ux/tui/commands.py`)

**Added research to help text**:

```python
SLASH_COMMANDS: dict[str, str] = {
    # ... other commands ...
    "/browser <query>": "Route query to Browser subagent",
    "/claude <query>": "Route query to Claude subagent",
    "/research <query>": "Route query to Research subagent",  # ← NEW
    "/skillify <query>": "Route query to Skillify subagent",
    "/weaver <query>": "Route query to Weaver subagent",
}
```

**Impact**: `/help` now shows `/research` command, improving discoverability.

## Usage Patterns

The slash command system supports both **prefix** and **inline** usage:

### Prefix Mode
```bash
> /research What is the meaning of balabalaxmx?
# Routes entire query to research subagent
```

### Inline Mode
```bash
> Can you /research the latest developments in quantum computing?
# Routes "Can you the latest developments in quantum computing?" to research subagent
# (subcommand removed from text)
```

### Multiple Inline Commands (First Wins)
```bash
> /browser check this site and /research its background
# Routes to browser subagent (first match wins)
```

## Technical Details

### Command Resolution Flow

1. **User Input**: `/research topic`
2. **TUI Parsing**: `parse_subagent_from_input()` detects `/research`
3. **Cleaned Text**: `"topic"` (command removed)
4. **Daemon Routing**: Sends `{"text": "topic", "subagent": "research"}`
5. **Runner Dispatch**: Routes to research subagent factory
6. **Research Execution**: Multi-source research with synthesis

### Integration Points

| Component | Location | Purpose |
|-----------|----------|---------|
| `SUBAGENT_FACTORIES` | `core/resolver/_resolver_tools.py` | Agent factory registration |
| `SUBAGENT_DISPLAY_NAMES` | `ux/cli/commands/subagent_names.py` | Name resolution for routing |
| `SLASH_COMMANDS` | `ux/tui/commands.py` | Help text and discovery |
| `parse_subagent_from_input()` | `ux/cli/commands/subagent_names.py` | Inline command parsing |

## Verification

All tests pass (919 passed, 2 skipped):

```bash
./scripts/verify_finally.sh
✓ Format check: PASSED
✓ Linting:       PASSED
✓ Unit tests:    PASSED
```

## Related

- **RFC-601**: Research subagent specification (conversion from tool to subagent)
- **IG-047**: Module self-containment refactoring
- **IG-052**: Event system optimization (research events registered)

## Future Work

The current slash command system works well but has a minor limitation:
- **First match wins**: If multiple subagent commands are present, only the first is used
- **Recommendation**: Consider adding warning or disallowing multiple subagent commands

## Lessons Learned

1. **Integration checklist**: When adding new subagents, check ALL registration points:
   - Factory registration (`SUBAGENT_FACTORIES`)
   - Display names (`SUBAGENT_DISPLAY_NAMES`)
   - Help text (`SLASH_COMMANDS`)
   - Plugin system (already covered via `@plugin` decorator)

2. **Discovery vs. registration**: Plugin system discovers subagents automatically, but manual registration in `SUBAGENT_FACTORIES` is still needed for backward compatibility during the transition period.

3. **User-facing integration**: Implementation completeness ≠ user accessibility. Always verify end-to-end user flows, not just backend implementation.