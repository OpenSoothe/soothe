# IG-688: Autopilot `top` Interactive Keymaps

**Created**: 2026-08-05  
**Status**: Implemented  
**Related**: [RFC-228 §autopilot_top](../specs/RFC-228-autopilot-job-ipc.md),
[IG-679](IG-679-autopilot-top-command.md),
[IG-686](IG-686-autopilot-job-artifacts-and-top-polish.md)

---

## Executive Summary

Polish `soothe autopilot top` with linux-`top` style single-char keymaps:

1. Toggle **all goals** (incl. terminal) vs **active-only** (`a` / `--all`).
2. Toggle nested **StepDAG** under goals (`s`).
3. Additional monitor keys: loops, density, delay, scroll, help, quit.

Stay on Rich `Live` (no Textual fullscreen). Destructive actions (pause/cancel)
remain out of scope.

---

## Problem

| Gap | Today |
|-----|--------|
| No interactive keys | Poll + Ctrl+C only (IG-686 out of scope) |
| Completed goals invisible | Server `TERMINAL_STATES` filter; empty params |
| Step DAG always on | Dense forests; no density control |
| Truncation only | Footer `… (truncated)` with no scroll |

---

## Design

### View state (CLI)

| Flag | Default | Key |
|------|---------|-----|
| `include_terminal` | `false` | `a` (also `--all`) |
| `show_steps` | `false` | `s` |
| `show_loops` | `true` | `l` |
| `interval` | `2.0` | `+` / `-` (also `--interval` / `-n`) |
| `scroll` | `0` | `j`/`k`, arrows, `g`/`G` |
| `help_open` | `false` | `h` / `?` |

`d` cycles density: `compact` (no steps/loops) → `steps` (steps on, loops off)
→ `full` (both on).

### Wire — `include_terminal`

```text
autopilot_top params: { include_terminal?: bool }  # default false
```

| `include_terminal` | Goals | Steps | Loops |
|--------------------|-------|-------|-------|
| `false` (default) | Non-`TERMINAL_STATES` only; omit fully terminal jobs | Full StepDAG under kept goals | `status == "active"` |
| `true` | Full `dag_snapshot` nodes/edges; include all-terminal jobs | Full StepDAG | Still active-only |

Server remains SoT for goal/loop filtering. Client `s` toggles StepDAG
visibility under goals that remain in the forest (do not strip completed
steps from live goals — that made `steps=on` empty after a plan wave).

### Input loop

Keep `Live(screen=True)`. Between polls, drain stdin with short `select`
timeouts (cbreak/raw). Keys update view state and redraw immediately when
possible; `Space` forces an RPC refresh.

Footer shows live bindings + mode badges (`mode=active (live)|all`,
`steps=on|off`, `loops=on|off`, `delay=Ns`). Active mode badge is emphasized
green; `a` footer hint flips between All ↔ Active.

### Keymap

| Key | Action |
|-----|--------|
| `q` / `Q` | Quit (Ctrl+C still works) |
| `h` / `?` | Help overlay; any key dismisses |
| `a` | Toggle all goals ↔ active-only |
| `s` | Toggle StepDAG |
| `l` | Toggle loops |
| `d` | Cycle density compact → steps → full |
| `+` / `-` | Faster / slower refresh (clamp 0.2–10s) |
| `Space` | Force refresh |
| `j` / `↓` | Scroll down |
| `k` / `↑` | Scroll up |
| `g` / `G` | Scroll top / bottom |

### Out of scope

Pause/cancel keys, per-goal expand cursor, push via `autopilot_subscribe`,
inactive loop history, Textual rewrite.

---

## Implementation plan

1. **Host** — `build_top_job_entry(..., include_terminal=)` /
   `AutopilotService.top_snapshot(*, include_terminal=)`.
2. **Daemon** — `AutopilotTopParams.include_terminal`; pass through
   `run_autopilot_action(..., "top")`.
3. **Client** — `autopilot_top(include_terminal=False)` + params model.
4. **CLI** — `TopViewState`, keymap drain, render flags, `--all`, footer/help.
5. **Docs** — this IG; RFC-228 / asyncapi params note.
6. **Tests** — snapshot include_terminal; CLI render toggles + keymap; daemon
   params validate.
7. **Verify** — cleanse → `./scripts/verify_finally.sh` → fix.

---

## Acceptance

- [x] `a` / `--all` shows terminal goals; default remains active-only
- [x] `s` / `l` / `d` control StepDAG and loops without wire changes
- [x] Default view: `show_steps=false`, `interval=2.0` (`--interval` / `-n`)
- [x] `q`/`h`/`+/-`/`Space`/scroll work in fullscreen Live
- [x] Footer/help document bindings; no IG/RFC ids in user-visible strings
- [x] Unit tests green; `./scripts/verify_finally.sh` green

---

## Cleanse notes

- Shared `_children_from_edges` for `job` DAG + `top` forest (removed
  duplicate adjacency loop in `_render_dag_tree`).
- Host `_copy_dag` for the `include_terminal` path (no parallel node/edge
  copy blocks).
- IG-679 / IG-686 out-of-scope keymaps/`--all` pointed at this IG.

| Area | Path |
|------|------|
| IG | `docs/impl/IG-688-autopilot-top-interactive-keymaps.md` |
| Host filter | `packages/soothe/src/soothe/autopilot/top_snapshot.py` |
| Host service | `packages/soothe/src/soothe/autopilot/service.py` |
| Daemon | `packages/soothe-daemon/src/soothe_daemon/protocol/` |
| Client | `client/python/src/soothe_client/` |
| CLI | `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py` |
| Spec | `docs/specs/RFC-228-autopilot-job-ipc.md`, `docs/specs/asyncapi.yaml` |
