# IG-170: Daemon-backed skill list and selection (remote-safe)

**Status**: Implemented  
**Date**: 2026-04-14

## Goal

Expose skill metadata and `SKILL.md`-based invocation through the daemon WebSocket so remote TUI clients do not depend on local filesystem paths. Local (in-process) TUI keeps filesystem discovery.

## Work completed

1. **`soothe.skills.catalog`** (pre-existing in this branch): shared enumeration, wire rows, resolve, read markdown, invocation envelope.
2. **`message_router`**: `skills_list` → `skills_list_response`; `invoke_skill` → `invoke_skill_response` (with `echo`) then queue composed prompt as `input`.
3. **`protocol_v2.validate_message`**: structural checks for `skills_list` and `invoke_skill`.
4. **RFC-400**: Documented message types, fields, error codes, and ordering rule (`invoke_skill_response` before stream events).
5. **`WebSocketClient` / `TuiDaemonSession`**: `list_skills` / `invoke_skill` via `request_response`.
6. **`execute_task_textual`**: `skip_daemon_send_turn` to stream without a second `send_turn` after daemon-queued skill turns.
7. **TUI `app.py`**: Daemon-ready fetch of skill list; slash autocomplete from daemon rows when applicable; bare `/skill:` lists daemon or local catalog; named `/skill:` on daemon uses RPC + stream attach; `/reload` refreshes daemon catalog when connected; startup skill with `-m` uses daemon RPC when appropriate.
8. **`command_registry.build_skill_commands_from_wire`**: Autocomplete from wire rows.

## Verification

Run `./scripts/verify_finally.sh` before merge.
