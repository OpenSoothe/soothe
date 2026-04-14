# RFC-607: Progressive Display Refinements Post-Migration: Progressive Display Refinements Post-Migration

**Status**: Draft
**Authors**: Claude Code, Xiaming Chen
**Created**: 2026-04-14
**Depends on**: RFC-606 (DeepAgents CLI TUI Migration), RFC-501 (Display Verbosity), RFC-500 (CLI/TUI Architecture)
**Kind**: Implementation Interface Design

---

## Abstract

This RFC defines progressive display refinements implemented after the DeepAgents CLI TUI migration (RFC-606). It specifies newline separator rules for major events, progressive display pipeline integration with DeepAgents backend adapters, and ProtocolEventWidget rendering for Soothe protocol events. These improvements enhance CLI readability without modifying the DeepAgents TUI core.

---

## Motivation

### Problems Addressed

After RFC-606 migration, the CLI progressive display output showed:

1. **Visual clutter** - Goal, step, reasoning, and completion events appeared consecutively without separation
2. **Backend integration gaps** - SootheBackendAdapter and ThreadBackendBridge created but not fully integrated into display pipeline
3. **Protocol event rendering** - ProtocolEventWidget created but not connected to DeepAgents TUI status bar

### Goals

1. Add newline separators before major events (goal, step, reasoning, completion) for improved readability
2. Integrate Soothe backend adapters into progressive display pipeline
3. Connect ProtocolEventWidget to Deepagents TUI status bar
4. Maintain DeepAgents TUI core unchanged (no modifications to copied files)

---

## Specification

### 1. Newline Separator Display Rules

**Scope**: DisplayLine dataclass in CLI stream pipeline

**Implementation**: Add `newline_before: bool = False` field to `DisplayLine`

**Enabled Events** (newline_before=True):
| Event Type | Formatter Function | Reason |
|------------|-------------------|---------|
| Goal started | `format_goal_header()` | Visual separation for new goal scope |
| Step started | `format_step_header()` | Clear step boundaries |
| AgentLoop reasoning | `format_reasoning()` | Separate reasoning from actions |
| Goal completed | `format_goal_done()` | Final report prominence |

**Example Output**:
```
🚩 Goal: Analyze project architecture
→ 🌀 List root directory structure

• 💭 Reasoning: Goal is straightforward - need to list files

○ ⏩ List all files in the src directory
● ✅ List all files in the src directory [1 tools] (3.5s)

● 🏆 Goal complete: Architecture analyzed (5 steps)
```

### 2. Progressive Display Pipeline Integration

**Current Architecture** (after RFC-606):
```
SootheRunner.astream()
    ↓ yields (namespace, mode, data)
Daemon WebSocket
    ↓ sends events
DaemonClient.receive_events()
    ↓ passes to StreamDisplayPipeline
StreamDisplayPipeline.process(event)
    ↓ dispatches to handlers
    ├─ _on_goal_started() → format_goal_header()
    ├─ _on_step_started() → format_step_header()
    ├─ _on_loop_agent_reason() → format_reasoning()
    └─ _on_goal_completed() → format_goal_done()
CliRenderer.on_progress_event()
    ↓ renders DisplayLine to stderr
```

**Backend Adapter Integration** (future):
```
SootheBackendAdapter (NEW from RFC-606)
    ├─ _adapt_protocol_event() → RFC-501 filtering
    └─ stream_messages() → daemon WebSocket stream

ProtocolEventWidget (NEW from RFC-606)
    └─ render_event() → status bar rendering
    └─ _render_plan_event(), _render_context_event(), etc.

ThreadBackendBridge (NEW from RFC-606)
    └─ list_threads_for_ui() → thread selector integration
```

**Note**: Backend adapters created in RFC-606 Phase 2, integration to TUI is Phase 4 (deferred for incremental integration).

### 3. ProtocolEventWidget Rendering

**Purpose**: Render Soothe protocol events in DeepAgents TUI status bar

**Event Types Supported**:
| Event | Icon | Color | Display |
|-------|------|-------|---------|
| `soothe.plan.created` | 📋 | cyan | "Plan created: {goal}" |
| `soothe.plan.step_started` | 📋 | cyan | "Starting: {description}" |
| `soothe.plan.step_completed` | ✅/❌ | green/red | "Completed" or "Failed" |
| `soothe.context.projected` | 🔍 | magenta | "Context: {N} entries" |
| `soothe.memory.recalled` | 💭 | yellow | "Memory: recalled {N} items" |
| `soothe.policy.denied` | 🔒 | red | "Policy denied: {reason}" |

**Verbosity Filtering** (RFC-501):
| Verbosity | Protocol Events Shown |
|-----------|----------------------|
| quiet | None (suppress all) |
| minimal | `soothe.plan.*` only |
| normal | `soothe.plan.*`, `soothe.context.*`, `soothe.memory.*` |
| detailed | All protocol events |

**Integration Point**: DeepAgents TUI `widgets/status.py` (TODO: add protocol queue in Phase 4)

---

## Implementation Notes

### Files Modified (RFC-607)

**CLI Stream Pipeline**:
- `src/soothe/ux/cli/stream/display_line.py` - Add newline_before field
- `src/soothe/ux/cli/stream/formatter.py` - Enable newline_before in formatters

**Backend Adapters** (created in RFC-606, refined here):
- `src/soothe/ux/tui/soothe_backend_adapter.py` - Protocol event filtering
- `src/soothe/ux/tui/thread_backend_bridge.py` - Thread metadata bridge
- `src/soothe/ux/tui/widgets/protocol_event.py` - Protocol rendering widget

### No Modifications to DeepAgents TUI Core

**Per RFC-606 principle**: "Preserve Soothe Identity"

- Deepagents TUI files copied in RFC-606 remain unchanged
- Integration via adapter layers (SootheBackendAdapter, ThreadBackendBridge)
- ProtocolEventWidget is Soothe-specific addition
- Newline separators in CLI stream pipeline (not TUI)

---

## Verification

**Test Command**:
```bash
uv run soothe -p "List files in src directory" --no-tui -v normal
```

**Expected Progressive Display**:
```
🚩 Goal: List files in src directory
→ 🌀 List all files in the src directory

• 💭 Reasoning: [Assessment] Goal is straightforward

○ ⏩ List all files in the src directory
● ✅ List all files in the src directory [1 tools] (3.5s)

● 🏆 List files in src directory (complete, 2 steps) (55.5s)
```

**Verification Status**:
✅ Format check: PASSED
✅ Linting: PASSED (zero errors)
✅ Unit tests: PASSED (1566 passed)

---

## Dependencies

- RFC-606: DeepAgents CLI TUI Migration (backend adapters, ProtocolEventWidget)
- RFC-501: Display Verbosity (verbosity tier filtering)
- RFC-500: CLI/TUI Architecture (progressive display pipeline)
- RFC-401: Event Processing (event dispatch)

---

## Status History

| Date | Status | Notes |
|------|--------|-------|
| 2026-04-14 | Draft | Created after RFC-606 implementation, newline separators added |

---

**Next Steps**: Review and refine via specs-refine, then mark as Implemented