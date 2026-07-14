# IG-340: Explore Subagent — Deduplicate Completed Events and Fix Workspace Propagation

## Problem

Two bugs in the explore subagent:

### 1. Duplicated "Completed" display lines

When the explore subagent runs as a Task tool:
- The explore engine emits `ExploreCompletedEvent` (`soothe.subagent.explore.completed`) in `synthesize_node`, rendered by `StreamDisplayPipeline._dispatch_curated_subagent_wire` -> `_on_subagent_completed`.
- The task ToolMessage result is rendered by `CliRenderer.on_tool_result`, joining the pending tool call line with the SubagentFormatter brief.

Both produce: `Task(explore, "...") -> Completed (Nms)`.

### 2. Wrong workspace

The AgentLoop executor passes `workspace` in `config.configurable`, not in the graph state. The task tool patch (`_patch.py`) copies `runtime.state` to subagent state but `workspace` is in `runtime.config.configurable`. The explore engine falls back to resolver workspace (daemon directory).

## Fix

### Fix 1: Suppress wire `*.completed` display when inside Task scope

In `StreamDisplayPipeline._dispatch_curated_subagent_wire()`, when a run-level `*.completed` event has a `task_scope`, return empty lines. The task ToolMessage result path produces the authoritative completion line with full duration.

### Fix 2: Propagate workspace from config to subagent state

In `_patch.py._validate_and_prepare_state()`, extract `workspace` from `runtime.config["configurable"]` and inject into subagent state when present.

## Status

- [x] Analysis
- [x] Implementation
- [x] Verification
