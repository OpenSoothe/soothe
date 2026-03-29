# RFC-0024: VerbosityTier Unification

**RFC**: 0024
**Title**: VerbosityTier Unification
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-29
**Updated**: 2026-03-29
**Dependencies**: RFC-0015
**Supersedes**: ---

## Abstract

This RFC defines a unified `VerbosityTier` enum that replaces the two-layer event classification system (event → ProgressCategory → VerbosityLevel) with direct classification (event → VerbosityTier). The design eliminates duplicate enums, simplifies classification logic from ~117 lines to ~25 lines, and uses integer comparison instead of set membership checks for visibility determination.

## Scope and Non-Goals

### Scope

This RFC defines:

* `VerbosityTier` enum with five tiers: `QUIET`, `NORMAL`, `DETAILED`, `DEBUG`, `INTERNAL`
* `should_show(tier, verbosity)` function using integer comparison
* `classify_event_to_tier()` function for direct event classification
* Integration with the event registry (`EventMeta.verbosity`)
* Migration path from `ProgressCategory` and `EventCategory` to `VerbosityTier`

### Non-Goals

This RFC does **not** define:

* New event types (see RFC-0015)
* Rendering logic for events (see RFC-0020)
* Content filtering policy (retained in DisplayPolicy)
* Wire protocol changes (IPC format unchanged)

## Background & Motivation

### Problem

The current verbosity classification system uses a two-layer approach:

1. **Event → ProgressCategory**: `classify_custom_event()` maps event types to 11 intermediate categories
2. **ProgressCategory → VerbosityLevel**: `should_show()` uses set membership to check visibility

This creates unnecessary complexity:

- ~117 lines of conditional logic in `classify_custom_event()`
- Duplicate enums: `ProgressCategory` (in `progress_verbosity.py`) and `EventCategory` (in `display_policy.py`) with identical 11 values
- Indirect mapping: registry stores intermediate strings, not final visibility levels
- Hardcoded strings in message component checks (`"protocol"`, `"assistant_text"`)
- O(n) set membership checks instead of O(1) comparison

### Solution

Replace the two-layer system with a unified `VerbosityTier` enum:

```
Event/Component → VerbosityTier → should_show(tier, verbosity)
```

A single integer comparison (`tier <= verbosity`) replaces set membership checks.

## Design Principles

### Principle 1: Direct classification

Events classify directly to a visibility tier, not an intermediate category. The tier is the minimum verbosity at which the event is visible.

### Principle 2: Unified type

A single `VerbosityTier` enum serves both event classification and message component visibility checks, eliminating duplicate enums.

### Principle 3: Ordered comparison

Tier values are integers enabling `<=` comparison. A tier of `NORMAL` (1) is visible at verbosity `normal` (1), `detailed` (2), and `debug` (3).

### Principle 4: Registry as source of truth

Events register their tier in the event registry. Unregistered events fall back to domain-based defaults.

## Specification

### VerbosityTier Enum

**Location**: `src/soothe/ux/core/verbosity_tier.py` (new file)

```python
from enum import IntEnum
from typing import Literal

VerbosityLevel = Literal["quiet", "normal", "detailed", "debug"]

class VerbosityTier(IntEnum):
    """Minimum verbosity level at which content is visible.

    Values are ordered so comparison works: tier <= verbosity means visible.
    """
    QUIET = 0      # Always visible (errors, assistant text, final reports)
    NORMAL = 1     # Standard progress (plan updates, milestones, agentic loop)
    DETAILED = 2   # Detailed internals (protocol events, tool calls, subagent activity)
    DEBUG = 3      # Everything including internals (thinking, heartbeats)
    INTERNAL = 99  # Never shown at any level (implementation details)
```

### Visibility Check

```python
_VERBOSITY_LEVEL_VALUES: dict[VerbosityLevel, int] = {
    "quiet": 0,
    "normal": 1,
    "detailed": 2,
    "debug": 3,
}

def should_show(tier: VerbosityTier, verbosity: VerbosityLevel) -> bool:
    """Return True if tier is visible at the given verbosity.

    Args:
        tier: The minimum verbosity level for this content.
        verbosity: User's current verbosity setting.

    Returns:
        True if content should be displayed.
    """
    if tier == VerbosityTier.INTERNAL:
        return False
    return tier <= _VERBOSITY_LEVEL_VALUES[verbosity]
```

### Event Classification

```python
def classify_event_to_tier(event_type: str, namespace: tuple[str, ...] = ()) -> VerbosityTier:
    """Classify an event directly to a VerbosityTier.

    Args:
        event_type: The event type string.
        namespace: Subagent namespace tuple (for non-soothe events).

    Returns:
        VerbosityTier for the event.
    """
    from soothe.core.event_catalog import REGISTRY

    # Registry lookup for soothe.* events
    if event_type.startswith("soothe."):
        return REGISTRY.get_verbosity(event_type)

    # Non-soothe events (from subagents like deepagents)
    if namespace:
        if "thinking" in event_type or "heartbeat" in event_type:
            return VerbosityTier.DEBUG
        return VerbosityTier.DETAILED

    # Unknown external events
    if "thinking" in event_type or "heartbeat" in event_type:
        return VerbosityTier.DEBUG
    return VerbosityTier.DEBUG
```

### Event Registry Integration

**Location**: `src/soothe/core/event_catalog.py`

The `EventMeta.verbosity` field changes from `ProgressCategory` (string) to `VerbosityTier` (enum).

```python
from soothe.ux.core.verbosity_tier import VerbosityTier

_DOMAIN_DEFAULT_TIER: dict[str, VerbosityTier] = {
    "lifecycle": VerbosityTier.DETAILED,
    "protocol": VerbosityTier.DETAILED,
    "cognition": VerbosityTier.NORMAL,
    "tool": VerbosityTier.DETAILED,
    "subagent": VerbosityTier.DETAILED,
    "output": VerbosityTier.QUIET,
    "error": VerbosityTier.QUIET,
    "agentic": VerbosityTier.NORMAL,
}

@dataclass(frozen=True)
class EventMeta:
    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier  # Changed from ProgressCategory
    summary_template: str = ""
```

### Message Component Integration

Message components use `VerbosityTier` directly:

| Component | VerbosityTier | Reason |
|-----------|---------------|--------|
| Tool calls/results | `DETAILED` | Internal details visible at detailed+ |
| Assistant text | `QUIET` | Always visible |
| Error messages | `QUIET` | Always visible |

### Migration Mapping

| Old ProgressCategory | New VerbosityTier | Notes |
|----------------------|-------------------|-------|
| `assistant_text` | `QUIET` | Always visible |
| `error` | `QUIET` | Always visible |
| `milestone` | `QUIET` | Completion milestones always visible |
| `plan_update` | `NORMAL` | Plan progress at normal+ |
| `subagent_progress` | `NORMAL` | Key subagent events at normal+ |
| `protocol` | `DETAILED` | Protocol internals at detailed+ |
| `tool_activity` | `DETAILED` | Tool calls/results at detailed+ |
| `subagent_custom` | `DETAILED` | Subagent internals at detailed+ |
| `thinking` | `DEBUG` | Internal thinking at debug only |
| `debug` | `DEBUG` | Debug info at debug only |
| `internal` | `INTERNAL` | Never shown |

## Files Changed

| File | Action | Description |
|------|--------|-------------|
| `ux/core/verbosity_tier.py` | **New** | VerbosityTier enum, should_show(), classify_event_to_tier() |
| `core/event_catalog.py` | **Modify** | EventMeta.verbosity type, domain defaults, all _reg() calls |
| `ux/core/progress_verbosity.py` | **Remove** | Delete file, functionality moved to verbosity_tier.py |
| `ux/core/display_policy.py` | **Modify** | Remove EventCategory, delegate to VerbosityTier |
| `ux/core/event_processor.py` | **Modify** | Replace string literals with VerbosityTier |
| `ux/core/message_processing.py` | **Modify** | Replace string literals with VerbosityTier |
| `ux/cli/renderer.py` | **Modify** | Replace string literals with VerbosityTier |
| `daemon/client_session.py` | **Modify** | Update should_show() signature |
| `ux/cli/execution/standalone.py` | **Modify** | Update classification usage |
| `tests/unit/test_progress_verbosity.py` | **Rewrite** | New tests for VerbosityTier system |

## Examples

### Event Registration

```python
# Agentic loop events
_reg("soothe.agentic.loop.started", AgenticLoopStartedEvent, verbosity=VerbosityTier.NORMAL)
_reg("soothe.agentic.loop.completed", AgenticLoopCompletedEvent, verbosity=VerbosityTier.QUIET)

# Output events
_reg(CHITCHAT_RESPONSE, ChitchatResponseEvent, verbosity=VerbosityTier.QUIET)
_reg(FINAL_REPORT, FinalReportEvent, verbosity=VerbosityTier.QUIET)

# Internal events
_reg(CHITCHAT_STARTED, ChitchatStartedEvent, verbosity=VerbosityTier.INTERNAL)
```

### Message Component Check

```python
# Before
if should_show("protocol", self._verbosity):
    render_tool_call(...)

# After
if should_show(VerbosityTier.DETAILED, self._verbosity):
    render_tool_call(...)
```

### Event Classification

```python
# Before
category = classify_custom_event(namespace, data)
if should_show(category, verbosity):
    ...

# After
tier = classify_event_to_tier(event_type, namespace)
if should_show(tier, verbosity):
    ...
```

## Relationship to Other RFCs

* **RFC-0015 (Progress Event Protocol)**: This RFC updates RFC-0015 by replacing `ProgressCategory` with `VerbosityTier`. The event registry and classification mechanism remain, but the verbosity field type changes.
* **RFC-0020 (Event Display Architecture)**: No changes to display architecture; only the classification mechanism changes.
* **RFC-0022 (Daemon-Side Event Filtering)**: The `should_show()` function signature changes but the filtering logic remains O(1).

## Open Questions

None.

## Conclusion

The `VerbosityTier` unification eliminates redundant intermediate classification, reduces code complexity, and provides a cleaner API for both event registration and message component visibility checks. The integer-based comparison is more intuitive and performant than set membership checks.

> **Events classify directly to visibility tiers, not intermediate categories.**