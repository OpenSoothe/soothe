# CLI TUI Implementation Guide

**Guide**: IG-007
**Title**: CLI Terminal User Interface Implementation
**Created**: 2026-03-12
**Related RFCs**: RFC-000, RFC-001, RFC-500

## Overview

This guide covers the implementation of the Soothe CLI TUI defined in RFC-500. The TUI provides
real-time streaming progress, protocol observability, thread management, and dynamic subagent
routing using Rich for terminal rendering.

## Prerequisites

- [x] RFC-000 accepted (System Conceptual Design)
- [x] RFC-001 accepted (Core Modules Architecture Design)
- [x] RFC-500 accepted (CLI TUI Architecture Design)
- [x] IG-005 completed (Core Protocols Implementation)
- [x] Development environment setup (deepagents >= 0.4.10, langgraph >= 1.1.1)

## File Structure

```
src/soothe/cli/
├── __init__.py          # MODIFY: export app
├── main.py              # MODIFY: TUI as default run mode, thread subcommands
├── runner.py            # NEW: SootheRunner (protocol orchestration + stream)
├── tui_shared.py        # NEW: shared TUI rendering/state helpers
├── tui_app.py           # NEW: Textual TUI client
├── commands.py          # NEW: Slash commands, subagent routing
└── thread_logger.py     # NEW: ThreadLogger (JSONL), InputHistory
```

## Implementation Plan

### Phase 1: Runner (SootheRunner)

**Goal**: Wrap `create_soothe_agent()` with protocol orchestration and provide
`astream()` that yields the deepagents-canonical `(namespace, mode, data)` stream
extended with `soothe.*` custom events.

**File**: `src/soothe/cli/runner.py`

Key design decisions:
- Extends deepagents' stream format, does not replace it
- Protocol events are `((), "custom", {"type": "soothe.*", ...})` plain dicts
- HITL interrupt loop follows `deepagents_cli/textual_adapter.py` pattern
- Thread ID is 8-char hex UUID matching deepagents convention
- Uses `MemorySaver` checkpointer (in-memory; production can swap to AsyncSqliteSaver)
- Enriched input prepends context + memories to user message content

### Phase 2: Commands and Session

**Goal**: Slash command handling, subagent routing, session logging, input history.

**Files**:
- `src/soothe/cli/commands.py` -- slash commands, subagent display names, numeric prefix parser
- `src/soothe/cli/thread_logger.py` -- JSONL thread logger, persistent input history

### Phase 3: TUI

**Goal**: Textual terminal UI consuming daemon-forwarded stream events.

**Files**:
- `src/soothe/cli/tui_app.py`
- `src/soothe/cli/tui_shared.py`

Key design decisions:
- Textual app provides always-on conversation/plan/activity panels
- Daemon-backed event transport decouples UI from runner lifecycle
- Shared parsing/rendering helpers live in `tui_shared.py` and are reused by commands

### Phase 4: CLI Integration

**Goal**: Wire TUI into the existing Typer CLI.

**File**: `src/soothe/cli/main.py`

Changes:
- `run` command: no prompt + no `--no-tui` -> launch TUI
- Add `--thread`, `--no-tui`, `--auto-approve` flags
- Add `thread` subcommand group (list, resume, archive)

## Implementation Details

### Stream dispatch pattern (TUI)

```python
async for namespace, mode, data in runner.astream(user_input, thread_id=thread_id):
    is_main = not namespace

    if mode == "messages" and is_main:
        msg, metadata = data
        if metadata and metadata.get("lc_source") == "summarization":
            continue
        if isinstance(msg, AIMessage) and hasattr(msg, "content_blocks"):
            for block in msg.content_blocks:
                if block.get("type") == "text":
                    state.full_response.append(block["text"])
                elif block.get("type") in ("tool_call_chunk", "tool_call"):
                    _handle_tool_call_block(block, state)
        elif isinstance(msg, ToolMessage):
            _handle_tool_result(msg, state)

    elif mode == "custom":
        if isinstance(data, dict) and data.get("type", "").startswith("soothe."):
            _handle_protocol_event(data, state)
        elif not is_main:
            _handle_subagent_custom(namespace, data, state)

    elif mode == "updates":
        pass  # HITL handled inside runner

    live.update(_build_display(state))
```

### HITL interrupt loop (Runner)

```python
while True:
    interrupt_occurred = False
    pending_interrupts = {}

    async for chunk in self._agent.astream(
        stream_input,
        stream_mode=["messages", "updates", "custom"],
        subgraphs=True,
        config=config,
    ):
        namespace, mode, data = chunk
        if mode == "updates" and isinstance(data, dict) and "__interrupt__" in data:
            for interrupt_obj in data["__interrupt__"]:
                pending_interrupts[interrupt_obj.id] = interrupt_obj.value
                interrupt_occurred = True
        yield chunk

    if not interrupt_occurred:
        break

    resume_payload = {iid: {"decisions": [{"type": "approve"}]}
                      for iid in pending_interrupts}
    stream_input = Command(resume=resume_payload)
```

## Testing Strategy

### Unit Tests

- `tests/unit_tests/test_cli_runner.py` -- SootheRunner protocol orchestration with mock agent
- `tests/unit_tests/test_cli_commands.py` -- Slash command parsing, subagent prefix routing
- `tests/unit_tests/test_cli_session.py` -- ThreadLogger JSONL output, InputHistory persistence

### Integration Tests

- `tests/integration_tests/test_cli_tui.py` -- Full TUI flow with mock LLM

## Verification

- [ ] `SootheRunner.astream()` yields valid `(namespace, mode, data)` tuples
- [ ] Protocol events have correct `soothe.*` type prefixes
- [ ] HITL interrupt loop handles auto-approve correctly
- [ ] TUI renders tool calls, subagent progress, and protocol events
- [ ] Slash commands work (/help, /plan, /memory, /context, /thread)
- [ ] Subagent numeric prefix routing parses correctly
- [ ] Session logger writes valid JSONL
- [ ] Thread persistence via DurabilityProtocol works
- [ ] `soothe run` launches TUI; `soothe run "prompt"` runs headless
- [ ] ruff lint clean

## Related Documents

- [RFC-500](../specs/RFC-500-cli-tui-architecture.md) - CLI TUI Architecture Design
- [RFC-000](../specs/RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) - Core Modules Architecture Design
- [IG-005](./005-core-protocols-implementation.md) - Core Protocols Implementation
