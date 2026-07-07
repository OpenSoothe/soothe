# IG-197: Subagent task tool propagates parent RunnableConfig

## Problem

`deepagents` `task` tool calls `subagent.ainvoke(subagent_state)` without the parent `ToolRuntime.config`. Nested LangGraph runs then use a no-op `stream_writer`, so `emit_progress()` in subagent nodes (e.g. browser step events) never reaches the root `astream` / CLI.

## Approach

Monkey-patch `deepagents.middleware.subagents._build_task_tool` at import time (alongside existing deepagents patches) so `invoke` / `ainvoke` receive `runtime.config`.

## Verification

- Unit test: mock runnable records config passed to `ainvoke` / `invoke`.
- `./scripts/verify_finally.sh`

## Fix: PEP 563 vs task tool `runtime`

``soothe.core.agent._patch`` must **not** use ``from __future__ import annotations``. Otherwise
``ToolRuntime`` becomes a string annotation, ``StructuredTool._injected_args_keys`` does not
list ``runtime``, and Pydantic validation drops ``runtime`` from tool input before ``atask`` runs
(``TypeError: ... missing ... 'runtime'``). Upstream ``deepagents/middleware/subagents.py`` avoids
PEP 563 for the same reason.

## Related: browser `max_steps`

`BrowserSubagentConfig.max_steps` defaults to **10** (YAML `subagents.browser.config.max_steps`). The browser graph uses this when `create_browser_subagent(..., max_steps=None)`.
