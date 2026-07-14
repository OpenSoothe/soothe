# IG-208: TUI tool-call UI gated by logging verbosity

**Status:** Completed  
**Scope:** `soothe-cli` TUI message stream handling, shared display policy, and headless `EventProcessor` tool gating.

## Goal

- Show or hide **tool-call rows** (`ToolCallMessage`, `ToolMessage` completion, related file-op UI) based on **CLI/daemon `logging.verbosity`** (normalized via `normalize_verbosity`), **not** on LangGraph namespace (`ns_key`) or ad-hoc event rules.
- **Subgraph / task** streams: stop dropping the entire `messages` branch for non-root namespaces; suppress only **assistant text** from nested subgraphs when the user did not use explicit `/browser|/claude|/research` routing (avoids duplicate prose while allowing tool UI).

## Changes

- `display_policy.py`: `should_show_tool_call_ui(verbosity)` — `quiet` hides tool UI; `normal` / `detailed` / `debug` show it.
- `textual_adapter.py`: `show_tool_ui` from normalized verbosity; `suppress_subgraph_assistant_text` for text blocks only; tool blocks and `ToolMessage` gated by `show_tool_ui`; buffers still drained when tool UI is off.
- `event_processor.py`: Tool-call / tool-result emission uses `VerbosityTier.NORMAL` (aligned with `CliRenderer.on_tool_call` / `on_tool_result`), not `DETAILED`, so default verbosity shows LangChain tool lines on stderr.
- `event_processor.py`: `_handle_plan_created` / plan step hooks use `soothe_sdk.client.schemas.Plan` / `PlanStep` field names (`plan_id`, `step_id`) so plan events validate.

## Verification

- `./scripts/verify_finally.sh`
