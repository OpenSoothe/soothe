# IG-112: UX Layer Boundaries (CLI / TUI / Shared / Daemon Client)

## Purpose

Refactor `src/soothe/ux/` so boundaries are explicit:

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Shared** | `ux/shared/` | Presentation pipeline: event processing, display policy, tool formatting, config load for UX, subagent input routing (no Typer, no Textual). |
| **CLI** | `ux/cli/` | Typer commands, stdout/stderr, headless streaming, subprocess launcher for TUI. Behavior and flags stay as today. |
| **TUI** | `ux/tui/` | Textual widgets and layout; uses shared + client modules only (no imports from `ux.cli.commands` except re-export shims if any). |
| **Daemon client** | `ux/client/` | WebSocket session bootstrap shared by headless CLI and TUI (ready handshake, thread create/resume, subscribe). Depends on `soothe.daemon` transport types only. |

**Daemon server** (`soothe/daemon/`) may import **`ux.shared`** for message/presentation helpers only—not CLI or TUI.

## Non-goals

- Changing Typer command surfaces or headless exit codes.
- Changing daemon protocol on the wire.

## Tasks

- [x] Rename `ux/core` → `ux/shared` and update imports project-wide.
- [x] Move subagent routing constants/helpers to `ux/shared/subagent_routing.py`; keep `cli/commands/subagent_names.py` as backward-compatible re-exports.
- [x] Add `ux/client/session.py` with shared WebSocket bootstrap; use from `cli/execution/daemon.py` and `tui/app.py`.
- [x] Run `./scripts/verify_finally.sh`.

## Status

Completed.
