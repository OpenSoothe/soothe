# IG-342: Explore Task card — tool lines, AI summary, wire events match CLI

## Goal

When the explore subagent runs inside a `task` tool, the parent Task tool card’s subagent activity notes should mirror CLI output:

- Inner subgraph tool invocations: combined line `⚙ Task(explore):#N Tool(args) -> ✓ … (Nms)` (same assembly as `CliRenderer.on_tool_result`).
- Final structured assistant JSON: one line `⚙ Task(explore):#N <summary>` via `format_explore_task_json_blob_for_display`, appended to the Task card instead of a duplicate assistant bubble.
- Curated `soothe.subagent.explore.*` wire events: use `StreamDisplayPipeline` formatted lines (with Task scope prefix), not only the short `summarize_subagent_wire_activity` text.

## Status

- [x] Analysis
- [x] Implementation (`packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py`)
- [x] Verification (`./scripts/verify_finally.sh`)
- [x] Unit test `packages/soothe-cli/tests/unit/ux/tui/test_explore_task_card_cli_parity.py`
