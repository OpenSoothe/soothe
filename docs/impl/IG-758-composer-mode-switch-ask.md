# IG-758: Composer Mode Switch (Auto / Manual / Plan / Ask)

**Created**: 2026-08-20
**Status**: Draft
**Related**: RFC-622 (clarification relay), RFC-633 (planner review), IG-682 (composer plan mode)

## Problem

The status-bar composer badge shows a bare three-state word (`Auto` / `Manual` /
`Plan`) that is terse and does not tell the operator how to change it. There is
also no read-only mode: every turn runs with the full mutating tool surface, so
operators cannot safely ask "what does this repo do?" without granting write
permissions.

## Goal

1. Replace the badge with a Claude Code-style indicator: glyph + descriptive
   label + `(shift+Tab to cycle)` hint.
2. Add a fourth **ask** mode that executes read-only tools only, enforced via
   `soothe_nano`'s existing `interaction_mode="ask"`.

## Mode model

Four **mutually-exclusive** single-select states, cycled with **Shift+Tab**:

| Mode | Badge label | `clarification_mode` | `interaction_mode` | `preferred_subagent` |
|------|-------------|----------------------|--------------------|----------------------|
| `auto`   | `⏵⏵ auto clarification (shift+Tab to cycle)` | `auto`   | — (agent) | `None`    |
| `manual` (default) | `⏵⏵ manual clarification (shift+Tab to cycle)` | `manual` | — (agent) | `None` |
| `plan`   | `⏵⏵ plan mode (shift+Tab to cycle)`           | `auto`   | — (agent) | `planner` |
| `ask`    | `⏵⏵ ask mode (shift+Tab to cycle)`            | `auto`   | `ask`      | `None`    |

- `plan` keeps the IG-682 semantics: `preferred_subagent=planner` +
  `clarification_mode=auto` (planner review stays manual via
  `force_manual_origins`).
- `ask` sends `clarification_mode="auto"` so read-only Q&A does not interrupt;
  the write restriction comes entirely from `interaction_mode="ask"`.

## Ask enforcement

`soothe_nano` already ships `interaction_mode="ask"` (`builder.build(...,
interaction_mode="ask")`), which filters tools (`exclude_tool_groups=
{"execution","file_ops"}`), restricts subagents to `planner`, forces the `ask`
policy profile, swaps FS tools to the read-only list with deny-write
permissions, disables the general-purpose subagent, and appends the read-only
system-prompt block.

The daemon compiles **one graph per long-lived worker** and never rebuilds per
turn, so ask needs a second, lazily-compiled graph:

- In `SootheRunner`, generalize the build closure to
  `_build_core_agent(interaction_mode="agent")` and cache results keyed by
  `"agent"` / `"ask"` (built through the **host** `create_soothe_agent`, so host
  injections survive). Keep `self._core_agent` as the default entry.
- `_materialize_core_agent(interaction_mode=None)` selects and materializes the
  matching entry; `_run_strange_loop` passes the selected agent into
  `StrangeLoop(core_agent=...)` per turn.
- Both graphs share the runner's checkpointer. Because ask mode only changes
  tool/subagent data (bound to the model, not compiled as extra nodes), the two
  graphs share node structure and a checkpointer.

> **Verify at impl time**: the ask graph must resume an existing thread
> checkpoint cleanly. If LangGraph rejects a mid-thread mode switch, fall back
> to a distinct `:ask`-suffixed thread namespace and note it here.

## Wire plumbing

Add `interaction_mode` (`agent|ask`) mirroring `clarification_mode` at every hop:

- Client: `soothe_client/protocol_params.py`, `soothe_client/websocket.py`,
  `soothe_client/appkit/daemon_session.py`
- Daemon: `soothe_daemon/protocol/schemas.py`, `protocol/router.py`
  (`_queue_options_from_daemon_message`), `server/handlers.py`,
  `query/engine.py`, `runner/{thread,pool}_runner.py`, `runner/ray_actor.py`
- Runner: `soothe/protocols/runner.py` (`LoopRunRequest`),
  `soothe/runner/__init__.py` (`astream`), `runner/_runner_strange_loop.py`

## Scope

- `soothe_cli/tui/composer_mode.py` — add `ask`, 4-state order, wire resolver
  (2-tuple → `ComposerWireFields(clarification_mode, preferred_subagent,
  interaction_mode)`)
- `soothe_cli/tui/widgets/status.py` — badge label/hint + `.ask` CSS class
- `soothe_cli/tui/app/_execution.py`, `textual_adapter.py`, `app/_startup.py` —
  forward `interaction_mode`
- `soothe_cli/tui/app/_messages_mixin.py` — cycle unchanged (order-driven)
- Copy: `tui/commands/slash_commands.py`, `tui/widgets/help_screen.py`,
  `tui/tips.py`
- Tests under `packages/soothe-cli/tests/unit/ux/tui/` (mode map, cycle order,
  badge), daemon router normalization, runner ask-graph selection

## Non-goals

- Orthogonal axes / simultaneous plan+auto selection (stays four exclusive states)
- A new policy profile (reuse nano `interaction_mode`)
- Headless `--mode ask` (optional follow-up; headless does not forward
  `clarification_mode` today either)

## Verification

- `packages/soothe-cli` unit tests for composer mode / badge
- Daemon + runner tests asserting `interaction_mode="ask"` selects the read-only
  graph and mutating tools are absent

## Cleanse (same pass)

- Drop the `resolve_composer_wire_fields` 2-tuple in favor of the dataclass
  (single call site each in `_execution.py` / `_startup.py`)
- Remove stale three-state copy ("Auto → Manual → Plan") from help/tips
