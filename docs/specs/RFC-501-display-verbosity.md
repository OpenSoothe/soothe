# RFC-501: Display & Verbosity

**Status**: Draft
**Authors**: Soothe Team
**Created**: 2026-03-31
**Last Updated**: 2026-03-31
**Depends on**: RFC-500 (CLI/TUI Architecture), RFC-400 (Event Processing), RFC-502 (Unified Presentation Engine)
**Supersedes**: RFC-0020, RFC-0024
**Kind**: Implementation Interface Design

---

## 1. Abstract

This RFC defines the interface contracts for Soothe's display system, establishing verbosity tier classification and icon-first formatting rules. It consolidates the event display architecture (RFC-0020) and verbosity tier unification (RFC-0024) into a single implementation interface specification.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* VerbosityTier enum with five visibility levels
* Three-level tree display structure (goal → step → result)
* Visibility check interface using integer comparison
* Event display patterns and formatting rules
* Registry-driven display metadata

### 2.2 Non-Goals

This RFC does **not** define:

* RendererProtocol interface (see RFC-400)
* Event processing pipeline (see RFC-400)
* Daemon transport (see RFC-400)
* CLI/TUI architecture (see RFC-500)

---

## 3. Background & Motivation

### 3.1 Problems Solved

| Problem | Before | After |
|---------|--------|-------|
| Event classification | Two-layer (event → category → level) | Direct (event → tier) |
| Visibility check | O(n) set membership | O(1) integer comparison |
| Display hierarchy | Ad-hoc formatting | 3-level tree structure |
| Duplicate enums | ProgressCategory + EventCategory | Single VerbosityTier |

### 3.2 Design Goals

1. Direct classification: events → visibility tier
2. Unified type for both events and message components
3. Ordered comparison for visibility determination
4. Registry as single source of truth

---

## 4. Naming Conventions

### 4.1 VerbosityTier Enum

| Tier | Value | Visible At | Description |
|------|-------|------------|-------------|
| `QUIET` | 0 | All levels | Errors, final answer, assistant text |
| `NORMAL` | 1 | normal+ | Plan updates, milestones, tool summaries |
| `DETAILED` | 2 | detailed+ | Protocol events, tool calls, subagent internals |
| `DEBUG` | 3 | debug | Thinking, heartbeats, all internals |
| `INTERNAL` | 99 | Never | Implementation details, never displayed |

### 4.2 VerbosityLevel

```python
VerbosityLevel = Literal["quiet", "normal", "detailed", "debug"]
```

| Level | Value | Tiers Shown |
|-------|-------|-------------|
| quiet | 0 | QUIET only |
| normal | 1 | QUIET + NORMAL |
| detailed | 2 | QUIET + NORMAL + DETAILED |
| debug | 3 | All except INTERNAL |

---

## 5. Data Structures

### 5.1 VerbosityTier Enum

```python
from enum import IntEnum
from typing import Literal

VerbosityLevel = Literal["quiet", "normal", "detailed", "debug"]

class VerbosityTier(IntEnum):
    """Minimum verbosity level at which content is visible.

    Values are ordered so comparison works: tier <= verbosity means visible.
    """
    QUIET = 0      # Always visible
    NORMAL = 1     # Standard progress
    DETAILED = 2   # Detailed internals
    DEBUG = 3      # Everything including internals
    INTERNAL = 99  # Never shown
```

### 5.2 Visibility Check

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

### 5.3 Event Classification

```python
def classify_event_to_tier(
    event_type: str,
    namespace: tuple[str, ...] = (),
) -> VerbosityTier:
    """Classify an event directly to a VerbosityTier.

    Args:
        event_type: The event type string.
        namespace: Subagent namespace tuple.

    Returns:
        VerbosityTier for the event.
    """
    from soothe.core.event_catalog import REGISTRY

    # Registry lookup for soothe.* events
    if event_type.startswith("soothe."):
        return REGISTRY.get_verbosity(event_type)

    # Non-soothe events (from subagents)
    if "thinking" in event_type or "heartbeat" in event_type:
        return VerbosityTier.DEBUG

    return VerbosityTier.DETAILED
```

---

## 6. Interface Contracts

### 6.1 Domain Default Tiers

```python
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
```

### 6.2 EventMeta Integration

```python
@dataclass(frozen=True)
class EventMeta:
    type_string: str
    model: type[SootheEvent]
    domain: str
    component: str
    action: str
    verbosity: VerbosityTier
    summary_template: str = ""
```

---

## 7. Display Architecture

### 7.1 Icon-First Structure

| Level | Name | Icons | Content |
|-------|------|-------|---------|
| 1 | Primary progress | `●` | top-level action / completion |
| 2 | Pending action | `○` | next action or in-progress action |
| 3 | Reason/result | `→`, `✓`, `✗` | concise progress judgement or outcome |

### 7.2 Icon Reference

| Icon | Meaning |
|------|---------|
| `○` | pending/running |
| `●` | completed |
| `→` | progress reasoning |
| `✓` | success confirmation |
| `✗` | error/failure |

### 7.3 Canonical Display Format

```
● {description}
○ {step_description}
→ {progress_summary} (80% sure)
● {step_description} [2 tools] (3.2s)
● {description} (complete, 2 steps, 5.0s)

{assistant_final_response}
```

---

## 8. Implementation Patterns

### 8.1 Event Registration with Tier

```python
# Agentic loop events
register_event(
    AgenticLoopStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="● Goal: {goal}",
)

register_event(
    AgenticLoopCompletedEvent,
    verbosity=VerbosityTier.QUIET,
    summary_template="● Goal: {goal} (complete, {steps} steps)",
)

# Internal events
register_event(
    ChitchatStartedEvent,
    verbosity=VerbosityTier.INTERNAL,
    summary_template="",
)
```

### 8.2 Visibility Check in Renderer

```python
def on_progress_event(
    self,
    event_type: str,
    data: dict,
    *,
    namespace: tuple[str, ...],
) -> None:
    tier = classify_event_to_tier(event_type, namespace)
    if not should_show(tier, self._verbosity):
        return

    meta = REGISTRY.get_meta(event_type)
    if meta and meta.summary_template:
        summary = meta.summary_template.format_map(data)
        self._write_line(summary)
```

### 8.3 Message Component Check

```python
# Before
if should_show("protocol", self._verbosity):
    render_tool_call(...)

# After
if should_show(VerbosityTier.DETAILED, self._verbosity):
    render_tool_call(...)
```

---

## 9. Verbosity Behavior Summary

| Content | quiet | normal | detailed | debug |
|---------|-------|--------|----------|-------|
| Final answer | ✓ | ✓ | ✓ | ✓ |
| Errors | ✓ | ✓ | ✓ | ✓ |
| Plan updates | ✗ | ✓ | ✓ | ✓ |
| Tool summaries | ✗ | ✓ | ✓ | ✓ |
| Milestones | ✗ | ✓ | ✓ | ✓ |
| Protocol/lifecycle | ✗ | ✗ | ✓ | ✓ |
| Subagent internals | ✗ | ✗ | ✓ | ✓ |
| Thinking/heartbeats | ✗ | ✗ | ✗ | ✓ |

---

## 10. Formatting Rules

### 10.1 Width Constraints

| Constraint | Value |
|------------|-------|
| Default terminal width | 80 chars |
| Maximum summary | 50 chars |
| Maximum detail | 80 chars |
| Indentation | 2 spaces + connector |

### 10.2 Text Processing

- Normalize whitespace to single spaces
- Truncate at word boundaries with ellipsis (...)
- Remove internal JSON blocks, decorative filler
- Preserve factual correctness

### 10.3 Output Separation

- **Headless**: Every block begins with one empty line
- **TUI**: Equivalent visual separation via widget spacing

---

## 11. Migration Mapping

| Old ProgressCategory | New VerbosityTier |
|----------------------|-------------------|
| `assistant_text` | `QUIET` |
| `error` | `QUIET` |
| `milestone` | `QUIET` |
| `plan_update` | `NORMAL` |
| `subagent_progress` | `NORMAL` |
| `protocol` | `DETAILED` |
| `tool_activity` | `DETAILED` |
| `subagent_custom` | `DETAILED` |
| `thinking` | `DEBUG` |
| `debug` | `DEBUG` |
| `internal` | `INTERNAL` |

---

## 12. Examples

### 12.1 Tool Activity Display

```
  ⚙ ReadFile("config.yml")
     └ ✓ Read 2.3 KB (42 lines) (150ms)
```

**Verbosity**: `NORMAL`

### 12.2 Subagent Activity Display

```
  ⚙ browser_subagent("search for docs")
     └ ✓ Navigate to page | https://example.com
     └ ✓ Extract content | hello world
     └ ✓ Done (45.2s)
```

**Verbosity**: `NORMAL`

### 12.3 Agentic Loop Progress

| Event | Level | Tier | Template |
|-------|-------|------|----------|
| `loop.started` | 1 | `NORMAL` | `● Goal: {goal}` |
| `step.started` | 2 | `DETAILED` | `  └ Step {n}: {description}` |
| `step.completed` | 2 | `NORMAL` | `  ✓ Step {n} done ({duration}s)` |
| `loop.completed` | 1 | `QUIET` | `● Goal: {goal} (complete, {steps} steps)` |

---

## 13. Relationship to Other RFCs

* **RFC-500 (CLI/TUI Architecture)**: Renderer implementations
* **RFC-400 (Event Processing)**: EventProcessor uses verbosity filtering
* **RFC-101 (Tool Interface)**: Tool event naming patterns
* **RFC-400 (Daemon Communication)**: Transport for events

---

## 14. Open Questions

1. Should `register_event()` support tier inheritance for sub-events?
2. Maximum summary length configurable per surface?
3. Parallel tool call display: collapse or expand by default?

---

## 15. Conclusion

This RFC unifies Soothe's display and verbosity system:

- VerbosityTier enum replaces two-layer classification
- Integer comparison (`tier <= verbosity`) for visibility
- Three-level tree structure for consistent display
- Registry-driven metadata for extensibility

> **Events classify directly to visibility tiers; display is strictly three levels.**