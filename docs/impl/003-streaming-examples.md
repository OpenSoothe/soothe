# Streaming Examples: Real-Time Progress Output

**Status**: Active
**Created**: 2026-03-12

## Overview

Convert all examples from blocking `invoke()` to streaming `astream()` using the
deepagents-canonical pattern: `stream_mode=["messages", "updates", "custom"]` with
`subgraphs=True`. This adds real-time visibility into tool calls, LLM text generation,
and subagent custom events during execution.

## Background

The deepagents CLI (`deepagents_cli/non_interactive.py`) uses this exact streaming pattern:

```python
async for chunk in agent.astream(
    input,
    stream_mode=["messages", "updates"],
    subgraphs=True,
):
    namespace, stream_mode, data = chunk
```

We extend this with `"custom"` mode to also receive events from `get_stream_writer()`
inside CompiledSubAgent nodes (research, browser, claude).

## Stream Modes

| Mode | Data format | Content |
|------|------------|---------|
| `messages` | `(message_obj, metadata)` | LLM tokens (AIMessage) and tool results (ToolMessage) |
| `updates` | `{"node_name": {...}}` | Node outputs; also `__interrupt__` events |
| `custom` | `Any` | Custom events from `get_stream_writer()` in subagent nodes |

When `subgraphs=True`, each chunk is a 3-tuple `(namespace, mode, data)` where
`namespace` is `()` for the main agent and a non-empty tuple for subagents.

## Implementation

### Shared Helper: `examples/_streaming.py`

A reusable `run_with_streaming()` async function that:

1. Calls `agent.astream(input, stream_mode=["messages", "updates", "custom"], subgraphs=True)`
2. Dispatches each chunk by mode
3. For `messages` mode:
   - AIMessage with `content_blocks` of type `"text"`: prints text tokens incrementally
   - AIMessage with `content_blocks` of type `"tool_call"`: prints tool name
   - ToolMessage: prints truncated result preview
   - Skips `lc_source="summarization"` chunks (internal bookkeeping)
4. For `custom` mode: prints formatted custom events from subagent progress
5. For `updates` mode: handles `__interrupt__` events only

Filtering: by default only main-agent events are shown. Pass `show_subagents=True` to
also render subagent-level messages and custom events.

### Per-Example Changes

All examples convert from sync `main()` + `invoke()` to async `main()` + `run_with_streaming()`:

- `scout_example.py` -- shows tool calls (ls, read_file, grep) and AI text
- `planner_example.py` -- shows tool calls and planning text
- `research_example.py` -- `show_subagents=True` for custom research progress events
- `claude_example.py` -- `show_subagents=True` for custom claude progress events
- `browser_example.py` -- `show_subagents=True` for custom browser progress events

## Verification

- Run `scout_example.py` and confirm real-time tool call / AI text output
- Run `research_example.py` and confirm custom research events appear
- All unit tests continue to pass
