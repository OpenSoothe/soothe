# IG-451: Remove interactive HITL remnants

## Goal

Remove dead human-in-the-loop (HITL) code paths and documentation left after the product moved to **agent-in-the-loop** with in-process LangGraph interrupt auto-resume. Align specs and clients with runtime behavior.

Supersedes the interactive portions of [IG-412](IG-412-tui-coreagent-hitl.md) (IG-412 doc rewritten to describe auto-resume only).

## What was removed

### TUI (`soothe-cli`)

- `AskUserMenu` widget and `_ask_user_types.py` (never wired from the event pipeline)
- `_request_ask_user`, `_pending_ask_user_widget`, and related Ctrl+C / Escape / Shift+Tab branches
- Orphaned CSS: `.approval-menu`, `.approval-placeholder`, `.tool-approval-widget`, `.ask-user-menu`

### Daemon protocol clients

- `resume_interrupts` message type and send helpers (no Python daemon handler existed)
- Go: `ResumeInterruptsMessage`, `SendResumeInterrupts`, integration test
- TypeScript: `ResumeInterruptsMessage`, `sendResumeInterrupts`, protocol tests

### Documentation

- Updated RFC-500, RFC-606, query-processing-flow wiki, IG-408, IG-427, IG-402, user_guide
- Rewrote IG-412 as “interrupt auto-resume (interactive HITL removed)”

## What remains (intentional)

| Piece | Role |
|-------|------|
| `Executor._core_agent_astream_with_interrupt_resume` | Detect `__interrupt__` on `updates`, auto-resume via `Command(resume=...)` |
| `graph_interrupt.build_auto_resume_payload` | Approve tool interrupts; empty `ask_user` answers |
| Stream coalescer / CLI `chunk_filter` | Keep `__interrupt__` chunks; drop noop `updates` otherwise |
| `interrupt_on` on `create_soothe_agent()` | Optional deepagents hook; unset on default path |

## Not in scope (future work)

- **`PolicyProtocol` `need_approval`**: middleware only blocks `deny`; `need_approval` is advisory
- **Goal `requires_confirmation`**: computed in criticality/semantic risk; not wired to pause execution
- **`TOOL_APPROVAL_*` preview limit names**: still used for non-blocking file-change previews (rename optional)
- **Analysis / conversation_history** stale HITL mentions

## Files touched

**Deleted**

- `packages/soothe-cli/src/soothe_cli/tui/widgets/ask_user.py`
- `packages/soothe-cli/src/soothe_cli/tui/_ask_user_types.py`

**CLI**

- `packages/soothe-cli/src/soothe_cli/tui/app/_app.py`, `_ui.py`, `_messages_mixin.py`, `_startup.py`, `app.tcss`
- `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py`, `runtime/wire/chunk_filter.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/file_change_preview.py`, `tui/theme.py`

**Clients**

- `client/go/protocol.go`, `send_methods.go`, `integration_loop_test.go`, `docs/`
- `client/typescript/src/protocol.ts`, `client.ts`, `index.ts`, `test/protocol.test.ts`

**Docs**

- `docs/impl/IG-412-tui-coreagent-hitl.md`, `docs/impl/IG-408-loop-client-isolation.md`, `IG-427`, `IG-402`
- `docs/specs/RFC-500-cli-tui-architecture.md`, `RFC-606-deepagents-cli-tui-migration.md`
- `docs/wiki/query-processing-flow.md`, `docs/user_guide.md`

## Verification

```bash
./scripts/verify_finally.sh
```

## Status

Completed.
