# VerbosityTier Unification Design

**Date**: 2026-03-29
**Status**: Phase 0 Draft
**Scope**: Event classification and message component visibility

## Problem Statement

The current system uses a two-layer classification approach:

1. **Event → ProgressCategory**: `classify_custom_event()` maps event types to 11 intermediate categories
2. **ProgressCategory → VerbosityLevel**: `should_show()` uses set membership to check visibility

This adds unnecessary complexity:

- ~117 lines of conditional logic in `classify_custom_event()`
- Duplicate enums: `ProgressCategory` (in `progress_verbosity.py`) and `EventCategory` (in `display_policy.py`) with identical values
- Indirect mapping: registry stores intermediate strings, not final visibility levels
- Hardcoded strings in message component checks (`"protocol"`, `"assistant_text"`)

## Solution

Replace the two-layer system with a unified `VerbosityTier` enum:

```
Event/Component → VerbosityTier → should_show(tier, verbosity)
```

A single integer comparison replaces set membership checks.

## Design

### VerbosityTier Definition

**Location**: `ux/core/verbosity_tier.py` (new file)

```python
from enum import IntEnum
from typing import Literal

# Define VerbosityLevel here to avoid circular imports
# display_policy.py will import from this module
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
        # Subagent-originated events
        if "thinking" in event_type or "heartbeat" in event_type:
            return VerbosityTier.DEBUG
        return VerbosityTier.DETAILED

    # Unknown external events
    if "thinking" in event_type or "heartbeat" in event_type:
        return VerbosityTier.DEBUG
    return VerbosityTier.DEBUG
```

### Event Registry Integration

**Location**: `core/event_catalog.py`

**Changes**:

1. Import `VerbosityTier` from new module
2. Change `EventMeta.verbosity` type from `ProgressCategory` to `VerbosityTier`
3. Update `_DOMAIN_DEFAULT_TIER` mapping
4. Update all `_reg()` calls

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
    """Metadata for a registered event type."""
    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier  # Changed from ProgressCategory
    summary_template: str = ""

def get_verbosity(self, event_type: str) -> VerbosityTier:
    """Return the VerbosityTier for an event type."""
    meta = self._by_type.get(event_type)
    if meta:
        return meta.verbosity
    domain = self.classify(event_type)
    return _DOMAIN_DEFAULT_TIER.get(domain, VerbosityTier.DEBUG)
```

**Event registration examples**:

```python
# Agentic loop events
_reg("soothe.agentic.loop.started", AgenticLoopStartedEvent, verbosity=VerbosityTier.NORMAL)
_reg("soothe.agentic.loop.completed", AgenticLoopCompletedEvent, verbosity=VerbosityTier.QUIET)
_reg("soothe.agentic.step.started", AgenticStepStartedEvent, verbosity=VerbosityTier.DETAILED)
_reg("soothe.agentic.step.completed", AgenticStepCompletedEvent, verbosity=VerbosityTier.NORMAL)

# Lifecycle events
_reg(THREAD_CREATED, ThreadCreatedEvent, verbosity=VerbosityTier.DETAILED)
_reg(DAEMON_HEARTBEAT, DaemonHeartbeatEvent, verbosity=VerbosityTier.DEBUG)

# Output events
_reg(CHITCHAT_STARTED, ChitchatStartedEvent, verbosity=VerbosityTier.INTERNAL)
_reg(CHITCHAT_RESPONSE, ChitchatResponseEvent, verbosity=VerbosityTier.QUIET)
_reg(FINAL_REPORT, FinalReportEvent, verbosity=VerbosityTier.QUIET)

# Error events
_reg(ERROR, GeneralErrorEvent, verbosity=VerbosityTier.QUIET)
```

### Message Component Changes

**Locations**: `ux/core/event_processor.py`, `ux/core/message_processing.py`, `ux/cli/renderer.py`

Replace hardcoded string checks with `VerbosityTier`:

| Current | New | Context |
|---------|-----|---------|
| `should_show("protocol", verbosity)` | `should_show(VerbosityTier.DETAILED, verbosity)` | Tool calls, tool results |
| `should_show("assistant_text", verbosity)` | `should_show(VerbosityTier.QUIET, verbosity)` | Assistant text content |
| `should_show("error", verbosity)` | `should_show(VerbosityTier.QUIET, verbosity)` | Error events |

**Example changes in event_processor.py**:

```python
# Before (line 237)
if name and should_show("protocol", self._verbosity):
    self._renderer.on_tool_call(name, coerced, tool_call_id, is_main=is_main)

# After
from soothe.ux.core.verbosity_tier import VerbosityTier, should_show

if name and should_show(VerbosityTier.DETAILED, self._verbosity):
    self._renderer.on_tool_call(name, coerced, tool_call_id, is_main=is_main)

# Before (line 292)
if not should_show("protocol", self._verbosity):
    return

# After
if not should_show(VerbosityTier.DETAILED, self._verbosity):
    return
```

### DisplayPolicy Unification

**Location**: `ux/core/display_policy.py`

**Changes**:

1. Remove `EventCategory` enum (11 values)
2. Import `VerbosityTier`, `should_show`, `classify_event_to_tier`
3. Update `_classify_event()` to return `VerbosityTier`
4. Update `_should_show_category()` → `_should_show_tier()`

```python
# Remove this enum entirely
# class EventCategory(Enum):
#     ASSISTANT_TEXT = auto()
#     PLAN_UPDATE = auto()
#     ... (11 values)

from soothe.ux.core.verbosity_tier import VerbosityTier, should_show, classify_event_to_tier

def _classify_event(self, event_type: str, namespace: tuple[str, ...] = ()) -> VerbosityTier:
    """Classify event directly to VerbosityTier."""
    return classify_event_to_tier(event_type, namespace)

def _should_show_tier(self, tier: VerbosityTier) -> bool:
    """Check if a tier should be shown at current verbosity."""
    return should_show(tier, self.verbosity)

def should_show_event(self, event_type: str, data: dict | None = None, namespace: tuple[str, ...] = ()) -> bool:
    """Determine if an event should be displayed."""
    if event_type in INTERNAL_EVENT_TYPES:
        return False
    if event_type in SKIP_EVENT_TYPES:
        return False
    tier = self._classify_event(event_type, namespace)
    return self._should_show_tier(tier)
```

### Progress Verbosity Cleanup

**Location**: `ux/core/progress_verbosity.py`

This file is **removed**. All functionality moves to `verbosity_tier.py`:

- `ProgressCategory` type alias → deleted
- `classify_custom_event()` → replaced by `classify_event_to_tier()`
- `should_show()` → moved to `verbosity_tier.py`

Update imports in all consumer files:

```python
# Before
from soothe.ux.core.progress_verbosity import classify_custom_event, should_show

# After
from soothe.ux.core.verbosity_tier import classify_event_to_tier, should_show, VerbosityTier
```

### Test Migration

**Location**: `tests/unit/test_progress_verbosity.py`

```python
"""Tests for VerbosityTier classification."""

from soothe.ux.core.verbosity_tier import (
    VerbosityTier,
    should_show,
    classify_event_to_tier,
)
from soothe.ux.core.verbosity_tier import VerbosityLevel  # Type alias for type hints


class TestVerbosityTier:
    def test_tier_ordering(self) -> None:
        assert VerbosityTier.QUIET < VerbosityTier.NORMAL
        assert VerbosityTier.NORMAL < VerbosityTier.DETAILED
        assert VerbosityTier.DETAILED < VerbosityTier.DEBUG
        assert VerbosityTier.INTERNAL > VerbosityTier.DEBUG

    def test_should_show_quiet(self) -> None:
        assert should_show(VerbosityTier.QUIET, "quiet")
        assert should_show(VerbosityTier.QUIET, "normal")
        assert should_show(VerbosityTier.QUIET, "detailed")
        assert should_show(VerbosityTier.QUIET, "debug")

    def test_should_show_normal(self) -> None:
        assert not should_show(VerbosityTier.NORMAL, "quiet")
        assert should_show(VerbosityTier.NORMAL, "normal")
        assert should_show(VerbosityTier.NORMAL, "detailed")
        assert should_show(VerbosityTier.NORMAL, "debug")

    def test_should_show_detailed(self) -> None:
        assert not should_show(VerbosityTier.DETAILED, "quiet")
        assert not should_show(VerbosityTier.DETAILED, "normal")
        assert should_show(VerbosityTier.DETAILED, "detailed")
        assert should_show(VerbosityTier.DETAILED, "debug")

    def test_should_show_debug(self) -> None:
        assert not should_show(VerbosityTier.DEBUG, "quiet")
        assert not should_show(VerbosityTier.DEBUG, "normal")
        assert not should_show(VerbosityTier.DEBUG, "detailed")
        assert should_show(VerbosityTier.DEBUG, "debug")

    def test_should_show_internal_never(self) -> None:
        """Internal events never shown at any verbosity."""
        assert not should_show(VerbosityTier.INTERNAL, "quiet")
        assert not should_show(VerbosityTier.INTERNAL, "normal")
        assert not should_show(VerbosityTier.INTERNAL, "detailed")
        assert not should_show(VerbosityTier.INTERNAL, "debug")

    def test_classify_agentic_events(self) -> None:
        assert classify_event_to_tier("soothe.agentic.loop.started") == VerbosityTier.NORMAL
        assert classify_event_to_tier("soothe.agentic.loop.completed") == VerbosityTier.QUIET
        assert classify_event_to_tier("soothe.agentic.step.started") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.agentic.step.completed") == VerbosityTier.NORMAL
        assert classify_event_to_tier("soothe.agentic.iteration.started") == VerbosityTier.DEBUG

    def test_classify_lifecycle_events(self) -> None:
        assert classify_event_to_tier("soothe.lifecycle.thread.created") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.lifecycle.daemon.heartbeat") == VerbosityTier.DEBUG

    def test_classify_protocol_events(self) -> None:
        assert classify_event_to_tier("soothe.protocol.context.projected") == VerbosityTier.DETAILED
        assert classify_event_to_tier("soothe.cognition.plan.created") == VerbosityTier.NORMAL

    def test_classify_output_events(self) -> None:
        assert classify_event_to_tier("soothe.output.chitchat.response") == VerbosityTier.QUIET
        assert classify_event_to_tier("soothe.output.autonomous.final_report") == VerbosityTier.QUIET
        assert classify_event_to_tier("soothe.output.chitchat.started") == VerbosityTier.INTERNAL

    def test_classify_error_events(self) -> None:
        assert classify_event_to_tier("soothe.error.general") == VerbosityTier.QUIET

    def test_classify_non_soothe_events(self) -> None:
        assert classify_event_to_tier("thinking.heartbeat", namespace=()) == VerbosityTier.DEBUG
        assert classify_event_to_tier("some_event", namespace=("tools:abc",)) == VerbosityTier.DETAILED
        assert classify_event_to_tier("unknown_event", namespace=()) == VerbosityTier.DEBUG
```

## Migration Mapping

### ProgressCategory → VerbosityTier

| ProgressCategory | VerbosityTier | Notes |
|------------------|---------------|-------|
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

## Benefits

1. **Simplified logic**: ~25 lines of classification code instead of ~117 lines
2. **Unified enum**: Single `VerbosityTier` replaces both `ProgressCategory` and `EventCategory`
3. **Direct mapping**: Events register their minimum visibility level directly
4. **Clear semantics**: `QUIET=0`, `NORMAL=1`, etc. — intuitive ordering
5. **O(1) comparison**: Integer comparison instead of set membership checks
6. **Plugin-friendly**: Third-party events register with explicit VerbosityTier
7. **Clean architecture**: No deprecated code, no backward-compat shims

## Risks

1. **Breaking change**: All callers of `should_show(category, verbosity)` must update
2. **Import updates**: Multiple files need new import statements
3. **Test migration**: Existing tests use ProgressCategory strings

## Mitigation

1. Run full test suite after migration to catch all callers
2. Update RFC-0015 documentation to reflect new VerbosityTier system
3. Single migration PR — no gradual rollout needed