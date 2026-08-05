# IG-679: Autopilot `top` Live Dashboard

**Created**: 2026-08-04  
**Status**: Implemented  
**Related**: [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md),
[IG-677](IG-677-autopilot-job-loop-index.md),
[IG-613](IG-613-protocol1-autopilot-request-rpcs.md),
[design draft](../drafts/2026-08-04-autopilot-top-command-design.md)

---

## Executive Summary

Add `soothe autopilot top`: a Rich `Live` CLI that polls one protocol-1 RPC
(`autopilot_top`) and redraws an **active-only** forest:

```text
Job (root) → Goal DAG → active JobLoopIndex loops
```

until Ctrl+C. Server owns filtering via CE `TERMINAL_STATES` and loop
`status == "active"`. Existing `status` / `job` / `goals` commands stay unchanged.

---

## Problem

Operators must stitch `status` + per-job `job <id>` + flat `goals` to see live
work. `list_job_loops` exists on `AutopilotService` but is not on the wire.
Multi-RPC client assembly would be chatty and easy to desync.

---

## Design

### Data flow

```text
soothe autopilot top  --poll-->  WS request method=autopilot_top
                                      │
                         run_autopilot_action(..., "top")
                                      │
                         AutopilotService.top_snapshot()
                         ├── status() header (running/dreaming/pool)
                         ├── roots + dag_snapshot(job_id)
                         └── list_job_loops(job_id) → active only
```

### Active filter (server SoT)

| Entity | Rule |
|--------|------|
| Job | Root ∉ `TERMINAL_STATES` **or** any descendant ∉ `TERMINAL_STATES` |
| Goal node | status ∉ `TERMINAL_STATES` (`completed`/`failed`/`cancelled`) |
| Edge | Both endpoints still in filtered node set |
| Loop | `JobLoopEntry.status == "active"` |
| Empty job | Omit after filter |

Blocked / suspended / awaiting_clarification goals **remain visible**.

### Wire

- Method: `autopilot_top` (protocol-1 `type=request`; optional
  `include_terminal` — IG-688)
- Result shape: RFC-228 §autopilot_top (`running`, `dreaming`, `loop_pool`,
  `generated_at`, `jobs[]` with `dag` + `loops`)

### CLI

| Item | Choice |
|------|--------|
| Command | `soothe autopilot top` |
| Flags | `--interval` / `-n` (default `1.0`, must be > 0) |
| UI | Rich `Live` clear/redraw |
| Quit | Ctrl+C |
| Empty | Header + “No active jobs” |
| Errors | Same `_require_daemon_ws` / non-zero exit on mid-session failure |

Render: reuse `_render_dag_tree` style; nest loops under matching `goal_id`;
orphan active loops (goal filtered out) under job root with `?` marker.

### Out of scope (v1)

Textual fullscreen, push via `autopilot_subscribe`, standalone
`list_job_loops` CLI. `--all` / interactive keys / scroll →
[IG-688](IG-688-autopilot-top-interactive-keymaps.md).

---

## Implementation plan

### 1. Host — `AutopilotService.top_snapshot()` (`soothe`)

Add async method on `packages/soothe/src/soothe/autopilot/service.py`:

1. Header from `status()` + UTC `generated_at`.
2. For each root goal: `dag_snapshot`, `list_job_loops`.
3. Apply filters above; return RFC-228 payload dict.

Prefer a small pure helper (e.g. `_filter_top_job(...)`) for unit testing
without a full service.

### 2. Daemon — protocol-1 plumbing (`soothe-daemon`)

| File | Change |
|------|--------|
| `protocol/autopilot_commands.py` | `action == "top"` → `await service.top_snapshot()` |
| `protocol/schemas.py` | `AutopilotTopParams` (+ `include_terminal` in IG-688) + PARAMS_REGISTRY |
| `protocol/router.py` | `_handle_autopilot_top` → `_dispatch_autopilot_rpc(..., "top")` |
| `docs/specs/asyncapi.yaml` | Document method (keep drift check green) |

### 3. Client stubs (submodules — consume/bump)

| Package | Change |
|---------|--------|
| `soothe-client-python` | `autopilot_top()` on async + sync clients; method map |
| `soothe-sdk` / client `protocol_params` | Empty params model if required by drift |
| TypeScript client (optional parity) | Same method when bumping clients |

Owned monorepo packages must not reverse the DAG; bump submodule pins after
client changes land in their repos (or land stubs in workspace submodules if
that is the current workflow).

### 4. CLI — `soothe autopilot top` (`soothe-cli`)

In `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py`:

1. `@app.command("top")` with `--interval`.
2. Poll `client.autopilot_top()` inside Rich `Live`.
3. Pure render helpers (header + forest) testable without Live.
4. Docstring: requires `soothed start`; Ctrl+C to quit.

### 5. Tests

| Package | Cases |
|---------|--------|
| `soothe` | Filter: terminal omitted; job kept for active descendant; edges pruned; loops under correct `goal_id`; empty forest |
| `soothe-daemon` | Registry accepts `autopilot_top`; dispatch smoke returns keys |
| `soothe-cli` | Render nesting / empty / interval validation |

Then `./scripts/verify_finally.sh` (cleanse → verify → fix).

---

## Acceptance

- [x] `AutopilotService.top_snapshot()` matches RFC-228 filter rules
- [x] `autopilot_top` registered and dispatched like other `autopilot_*` RPCs
- [x] Client can call `autopilot_top` over WS
- [x] `soothe autopilot top` live-refreshes until Ctrl+C
- [x] Existing autopilot CLI commands unchanged
- [x] Unit tests above green; `./scripts/verify_finally.sh` green

---

## Key files

| Area | Path |
|------|------|
| IG | `docs/impl/IG-679-autopilot-top-command.md` |
| Spec | `docs/specs/RFC-228-autopilot-job-ipc.md` (§autopilot_top) |
| Draft | `docs/drafts/2026-08-04-autopilot-top-command-design.md` |
| Service | `packages/soothe/src/soothe/autopilot/service.py` |
| Index | `packages/soothe/src/soothe/autopilot/job_loop_index.py` |
| Dispatch | `packages/soothe-daemon/src/soothe_daemon/protocol/autopilot_commands.py` |
| Schema / router | `packages/soothe-daemon/.../schemas.py`, `router.py` |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` |
| AsyncAPI | `docs/specs/asyncapi.yaml` |
