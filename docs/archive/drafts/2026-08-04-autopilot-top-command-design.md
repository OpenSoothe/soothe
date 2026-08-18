# Design Draft: Autopilot `top` Command

**Status**: Formalized → [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md)  
**Date**: 2026-08-04  
**Scope**: Live CLI dashboard (`soothe autopilot top`) showing active autopilot jobs, goal DAG relations, and assignment loops — linux-`top` style.  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md), [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md), [RFC-228](../specs/RFC-228-autopilot-job-ipc.md), [IG-677](../impl/IG-677-autopilot-job-loop-index.md), existing CLI `soothe autopilot status` / `job` / `goals`.

---

## Problem

Operators monitoring long-running autopilot work today must stitch together:

1. `soothe autopilot status` — coarse counts and a flat job list  
2. `soothe autopilot job <id>` — one-shot ASCII DAG for a single job  
3. `soothe autopilot goals` — flat goal list with optional parent hint  

There is no **live, multi-job** view of the full relation:

```text
Job (root goal) → Goal DAG → Loops (IG-677 assignments)
```

`JobLoopIndex.list_loops` exists on `AutopilotService` but is not exposed on the wire, so the CLI cannot show goal↔loop membership at all. Polling several RPCs per tick would be chatty and easy to desync.

---

## Goal

1. Add `soothe autopilot top`: a Rich `Live` refresh loop that redraws until Ctrl+C.  
2. Default view shows **active-only** jobs → non-terminal goals → `status == "active"` loops.  
3. One aggregate WS RPC supplies the filtered snapshot each tick (single round-trip).  
4. Keep existing `status` / `list` / `job` / `goals` commands unchanged.  
5. Stay in Typer CLI (no Textual fullscreen for v1).

---

## Non-Goals

- Interactive keys (cancel, focus, expand/collapse) in v1  
- `--all` / recent-terminal retention window (may follow later)  
- Event-push via `autopilot_subscribe` instead of polling  
- TUI `/autopilot` panel changes
- Changing GoalEngine / WorkerPool scheduling behavior  

---

## Decisions

| Topic | Decision |
|-------|----------|
| Interaction | Live refresh (linux-`top`); quit on Ctrl+C |
| Tree depth | Jobs → goal DAG → loops |
| Default filter | Non-`TERMINAL_STATES` goals/jobs; loops with `status == "active"` only |
| UI | Rich `Live` in `soothe-cli` |
| Data path | New aggregate RPC `autopilot_top` (approach #2) |
| Refresh | `--interval` / `-n`, default `1.0` seconds |
| Empty state | Header + “No active jobs” |
| Daemon down | Same `_require_daemon_ws` error + exit as other autopilot cmds |
| Mid-session disconnect | Print error, exit non-zero |
| Existing commands | Unchanged |

---

## Approaches considered

| # | Approach | Pros | Cons |
|---|----------|------|------|
| 1 | Client polls `status` + `list_jobs` + `get_job`×N (+ new loops RPC) | Minimal daemon surface | N+2 round-trips; filter duplicated in CLI; flicker risk |
| 2 | **Aggregate `autopilot_top` snapshot RPC** | One round-trip; server owns filter + tree shape | New wire method + client stubs |
| 3 | Event-driven `autopilot_subscribe` | Low latency | Incomplete DAG snapshot today; reconnect/state complexity |

**Decision: #2.**

---

## Architecture

```text
soothe autopilot top
        │
        │  Rich Live loop (poll interval)
        ▼
soothe-cli  ──WS──►  soothe-daemon  ──►  AutopilotService.top_snapshot()
                                              ├── status() / WorkerPool
                                              ├── CE goals + dag_snapshot
                                              └── JobLoopIndex (active loops)
```

Package placement (one-way DAG):

| Package | Change |
|---------|--------|
| `soothe` | `AutopilotService.top_snapshot()` |
| `soothe-daemon` | Router handler + request schema |
| `soothe-sdk` / `soothe-client-python` | Method name + params (submodule bump) |
| `soothe-cli` | `top` command + Rich renderer |

---

## Wire contract

### Request

- Method: `autopilot_top`
- Params: none (empty object)
- Type: `request`

### Response

```json
{
  "running": true,
  "dreaming": false,
  "loop_pool": {
    "active": 1,
    "idle": 0,
    "total": 1,
    "max": 4
  },
  "generated_at": "2026-08-04T01:00:00+00:00",
  "jobs": [
    {
      "id": "a1b2c3d4",
      "status": "active",
      "priority": 50,
      "description": "Implement auth",
      "workspace": "/path/to/ws",
      "dag": {
        "root_id": "a1b2c3d4",
        "nodes": [
          {
            "id": "a1b2c3d4",
            "description": "Implement auth",
            "status": "active",
            "priority": 50,
            "depends_on": [],
            "assigned_loop_id": "autopilot__a1b2c3d4__deadbeef…",
            "steps_completed": 1,
            "steps_total": 4,
            "tool_calls": 3
          }
        ],
        "edges": [
          {"source": "a1b2c3d4", "target": "e5f6…"}
        ]
      },
      "loops": [
        {
          "seq": 3,
          "loop_id": "autopilot__a1b2c3d4__deadbeef…",
          "goal_id": "e5f6…",
          "status": "active",
          "attempt": 1,
          "started_at": "…"
        }
      ]
    }
  ]
}
```

Header fields (`running`, `dreaming`, `loop_pool`) mirror `AutopilotService.status()` so the CLI does not need a second call.

### Active filter (server SoT)

| Entity | Include when |
|--------|----------------|
| Job | Root status ∉ `TERMINAL_STATES` **or** any descendant ∉ `TERMINAL_STATES` |
| Goal node | Goal status ∉ `TERMINAL_STATES` |
| Edge | Both endpoints remain in the filtered node set |
| Loop | `JobLoopEntry.status == "active"` |

Reuse CE’s existing `TERMINAL_STATES` (`completed`, `failed`, `cancelled` from `soothe.context.models`). Non-terminal includes `pending`, `active`, `awaiting_clarification`, `suspended`, and other live/blocked states — those stay visible in `top` (operators still need to see blocked work). Do not invent a parallel status list in the CLI.

Jobs with no remaining visible goals after filtering are omitted.

---

## Host API

```python
async def top_snapshot(self) -> dict[str, Any]:
    """Build active-only jobs → goals → loops snapshot for CLI top."""
```

Implementation sketch:

1. Start from `status()` for header fields; set `generated_at` (UTC ISO).  
2. Enumerate root goals (jobs).  
3. For each job, call existing `dag_snapshot(job_id)` and `list_job_loops(job_id)`.  
4. Apply active filters; drop empty jobs.  
5. Return the response shape above.

Optional reuse: attach active loops onto `get_job` later is **out of scope**; `top_snapshot` is the SoT for this command. `list_job_loops` may gain a thin wire alias only if another consumer needs it; v1 does not require a separate CLI command.

---

## CLI UX

### Command

```text
soothe autopilot top [--interval|-n FLOAT]
```

### Screen layout (each tick)

```text
Autopilot top · running · pool 1/0/4 (active/idle/max) · 2 jobs · 01:23:45
────────────────────────────────────────────────────────────────────────
[a1b2c3d4] active   pri=50  "Implement auth"
├─ [a1b2c3d4] active   "Implement auth"  steps 1/4
│  └─ loop autopilot__a1b2…__deadbeef  active  #3
├─ [e5f6aaaa] active   "Write tests"  steps 2/5
│  └─ loop autopilot__a1b2…__cafebabe  active  #4
└─ [9abcbbbb] pending  "Update docs"

[…]
────────────────────────────────────────────────────────────────────────
Ctrl+C quit · refresh 1.0s
```

Rendering rules:

- Reuse the ASCII tree style of `_render_dag_tree` in `autopilot_cmd.py`.  
- Nest loops under the goal matching `JobLoopEntry.goal_id`.  
- If a loop’s `goal_id` is missing from the filtered DAG (should be rare), show it under the job root with a `?` marker rather than dropping it silently.  
- Truncate descriptions with existing `preview_first`.  
- Shorten `loop_id` for display (keep enough suffix to distinguish) while printing full id only if needed later (`--verbose` out of scope for v1).

### Failure behavior

| Case | Behavior |
|------|----------|
| Daemon not running at start | Error + exit 1 |
| RPC failure mid-session | Exit Live, print error, exit 1 |
| Empty `jobs` | Still redraw header + empty message |
| Interval ≤ 0 | Typer validation error |

---

## Testing

| Layer | Cases |
|-------|--------|
| `soothe` unit | `top_snapshot` omits terminal jobs/goals/loops; keeps jobs with only active descendants; edges pruned correctly; loops attached to correct `goal_id` |
| `soothe-cli` unit | Tree render nesting; empty state; header fields present |
| Daemon light | Router accepts `autopilot_top` and returns the documented keys |

Do not weaken tests to match a buggy filter — fix the snapshot builder.

---

## Implementation sequence

1. `AutopilotService.top_snapshot()` + unit tests  
2. Daemon schema + router handler  
3. Client / sdk stubs (submodule)  
4. CLI `top` + Rich Live renderer + unit tests  
5. `./scripts/verify_finally.sh`  

---

## Open follow-ups (explicitly deferred)

- `--all` and/or recent-terminal retention  
- Interactive cancel/focus keys  
- Push updates via `autopilot_subscribe`  
- Expose `list_job_loops` as its own RPC/CLI if other tools need it  

---

## Success criteria

- [ ] `soothe autopilot top` live-refreshes active job→goal→loop trees until Ctrl+C  
- [ ] One WS round-trip per tick via `autopilot_top`  
- [ ] Terminal work is hidden by default  
- [ ] Existing autopilot CLI commands unchanged  
- [ ] Verify script green  
