# IG-196: Explicit subagent routing (TUI + slash commands)

## Goal

Ensure `/browser`, `/claude`, and `/research` set the WebSocket `subagent` field so `SootheRunner.astream` uses direct subagent routing (same behavior as headless `-p`).

## Changes

1. `command_router.handle_routing_command`: parse via `parse_subagent_from_input`, send cleaned text with `subagent=` when applicable; `/plan` unchanged (no subagent token).
2. `textual_adapter.execute_task_textual`: before `daemon_session.send_turn`, apply `parse_subagent_from_input` to the daemon-bound text.
3. `SystemPromptOptimizationMiddleware`: for explicit daemon quick-path (`routing_hint=subagent` + `preferred_subagent`), first model hop narrows tools to `task` only and strengthens `<SUBAGENT_ROUTING_DIRECTIVE>`; directive and narrowing drop after the first assistant/tool hop so synthesis can use the full tool set.

## Verification

Run `./scripts/verify_finally.sh`.
