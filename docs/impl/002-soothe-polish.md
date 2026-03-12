# Soothe Polish: Config, Browser-Use SubAgent, Claude SubAgent, and Progress Reporting

**Status**: Active
**Created**: 2026-03-12

## Overview

This guide covers polishing the Soothe project configuration layer, replacing the stub browser
subagent with a real `browser-use`-backed `CompiledSubAgent`, adding a new Claude Agent subagent
wrapping `claude-agent-sdk`, implementing progress reporting via LangGraph stream writer, and
fixing existing subagent bugs.

### Core Principles

1. **SOOTHE_ env prefix** -- all Soothe-specific config uses the `SOOTHE_` prefix via pydantic-settings.
2. **External agents as CompiledSubAgent** -- browser-use and claude-agent-sdk each manage their
   own LLM and tool loop; we wrap them as LangGraph StateGraphs exposed via `CompiledSubAgent`.
3. **Progress via stream writer** -- use `langgraph.config.get_stream_writer()` so consumers can
   see real-time progress from long-running subagents.
4. **Dependencies from PyPI** -- `browser-use` and `claude-agent-sdk` are pip-installed optional extras.
   The `thirdparty/` directories are source reference only.

## Phase 1: LLM Config Polish

### Changes to `SootheConfig`

Add LLM-related fields with `SOOTHE_` env prefix:

- `llm_provider` -- provider name (default `"openai"`)
- `llm_api_key` -- API key
- `llm_base_url` -- base URL for OpenAI-compatible endpoints
- `llm_chat_model` -- chat model name
- `llm_vision_model` -- vision model name

Add `resolve_model_string()` method returning `"provider:model"` format for `init_chat_model`.

### Changes to `.env`

Replace `NOESIUM_*` vars with `SOOTHE_*` equivalents. Keep `OPENAI_*` vars for browser-use
compatibility.

### Changes to `agent.py`

Use `config.resolve_model_string()` when no explicit model is passed. Propagate `llm_api_key`
and `llm_base_url` to `os.environ` for downstream library compatibility.

## Phase 2: Browser-Use SubAgent

Replace the stub `SubAgent` in `browser.py` with a `CompiledSubAgent` wrapping `browser_use.Agent`.

### Architecture

- `BrowserSubAgentState(TypedDict)` with `messages` key
- Single-node `StateGraph` that:
  1. Extracts task from last message
  2. Creates `browser_use.llm.openai.chat.ChatOpenAI` from env
  3. Creates `browser_use.Agent(task, llm, ...)` with configurable `BrowserProfile`
  4. Runs with `on_step_end` callback for progress reporting via `get_stream_writer()`
  5. Returns `AgentHistoryList.final_result()` as AI message

### Dependency

`browser-use>=0.12.0` as optional extra (replaces `cdp-use`).

## Phase 3: Claude Agent SubAgent

New `CompiledSubAgent` in `claude.py` wrapping `claude-agent-sdk` from PyPI.

### Architecture

- `ClaudeSubAgentState(TypedDict)` with `messages` key
- Single-node `StateGraph` that:
  1. Extracts task from last message
  2. Builds `ClaudeAgentOptions` with configurable model, permission_mode, max_turns, etc.
  3. Iterates `async for message in query(prompt, options)` with progress via `get_stream_writer()`
  4. Aggregates `TextBlock` content from `AssistantMessage` objects
  5. Returns aggregated text as AI message

### Dependency

`claude-agent-sdk>=0.1.40` as optional extra (from PyPI).

## Phase 4: Progress Reporting

Both browser and claude subagents use `langgraph.config.get_stream_writer()` to emit custom
streaming events during execution.

Consumer side: `agent.astream(input, stream_mode=["updates", "custom"])`.

Graceful degradation: if `get_stream_writer()` raises (not streaming), fall back to
`logging.info()`.

## Phase 5: Fix Existing SubAgents

- `scout.py`: fix any syntax errors and name typos
- `research.py`: remove hardcoded `"claude-sonnet-4-6"` default, accept resolved model from config
- `config.py`: add `"claude"` to default subagents (disabled)

## Phase 6: Update Examples and Tests

- Remove hardcoded model strings from examples
- Update `browser_example.py` for new browser-use integration
- Add `claude_example.py`
- Update unit tests for new config fields, subagent shapes

## Verification Checklist

- [ ] `SootheConfig` reads `SOOTHE_*` env vars correctly
- [ ] `resolve_model_string()` returns correct `"provider:model"` format
- [ ] Browser subagent returns `CompiledSubAgent` with `runnable` key
- [ ] Claude subagent returns `CompiledSubAgent` with `runnable` key
- [ ] Progress events emitted via `get_stream_writer()` during subagent execution
- [ ] All examples work with env-driven config
- [ ] All unit tests pass
