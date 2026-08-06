---
name: diagnose-loop
description: >-
  Diagnose Soothe agent loops from ~/.soothe/logs (soothe.log, daemon.log,
  cli.log) and per-loop runner.log. Analyzes StrangeLoop plans, CoreAgent
  write_todos, tool-call anomalies, and skill loading. Use when debugging
  loop hangs, failed steps, TUI mismatches, wasteful plans/todos, or skills
  not loaded. For autopilot jobs / goal DAG / rail / parallelism / job
  execution history, use the inspect-autopilot-job skill instead.
---

# Diagnose Loop

Systematic log forensics for Soothe **loops**, daemon lifecycle, and CLI/TUI.

For **autopilot jobs** (job id, rail, DAG, parallelism, goal execution
history), use [inspect-autopilot-job](../inspect-autopilot-job/SKILL.md).

## Routing

```text
if user mentions job id / autopilot / rail / pool / multi-goal / "low parallelism"
     / goal DAG / job execution history
  → inspect-autopilot-job (then Workflow B here on hot loops if needed)
else if specific loop id / suffix / hang / tools / plan / skills
  → Workflow B (and A if broad)
else
  → Workflow A broad triage
```

Prefer the **venv** CLI when available (`.venv/bin/soothe`).

## When to Use

- Loop hang, failed step, spinner stuck, or missing TUI progress
- Analyze `~/.soothe/logs/` or a specific loop (UUID or 4-char suffix)
- Tool errors, slow steps, repetitive tool calls
- StrangeLoop plan / CoreAgent todo waste
- Skill did not load, `/skill:name` failed, or skill instructions ignored

**Not this skill:** autopilot job DAG, rail conformance, pool parallelism,
job-level execution history → [inspect-autopilot-job](../inspect-autopilot-job/SKILL.md).

## Log Locations

| File | Logger / purpose | Loop correlation |
|------|------------------|------------------|
| `~/.soothe/logs/soothe.log` | `soothe.*` — StrangeLoop, CoreAgent, tools, planner | 4-char suffix `[7cba]` |
| `~/.soothe/logs/daemon.log` | `soothe_daemon.*` — WebSocket, workers | Full UUID `[loop=…]` |
| `~/.soothe/logs/cli.log` | `soothe_cli.*` — connection, TUI events | May include loop context |
| `~/.soothe/data/loops/{loop_id}/runner.log` | Same as soothe.log, one loop | Prefer for pooled workers |

Rotated backups: `*.log.1`, `*.log.2`, etc. Runtime defaults are `daemon.log`
and `cli.log` (not `soothed.log` / `soothe-cli.log`).

## Resolve Loop Identity

User may give full UUID, 4-char suffix (`7cba`), or step id prefix (`UZH-01`).

```bash
soothe loop list
ls ~/.soothe/data/loops/ | grep -i '<suffix>'
rg '\[<suffix>\]' ~/.soothe/logs/soothe.log*
rg 'loop=.*<suffix>' ~/.soothe/logs/daemon.log*
```

Record: full `loop_id`, time range, worker id (`thread-worker-0`), goal index.

## Workflow A — Broad Log Triage

Run in parallel, then correlate timestamps.

### 1. soothe.log

```bash
rg -i 'error|exception|failed|Traceback' ~/.soothe/logs/soothe.log* | tail -80
rg '^\d{4}-\d{2}-\d{2}.*\[[0-9a-f]{4}\]' ~/.soothe/logs/soothe.log* | tail -30
rg '\[Loop\]|\[Plan\]|\[Execute\]' ~/.soothe/logs/soothe.log* | tail -50
rg '\[Plan\] phase=' ~/.soothe/logs/soothe.log* | tail -40
```

### 2. daemon.log

```bash
rg 'loop_new|loop_input|thread-worker|completed request|Worker thread exited' \
  ~/.soothe/logs/daemon.log* | tail -80
rg -i 'error|exception|failed|timeout' ~/.soothe/logs/daemon.log* | tail -50
rg 'thread-worker.*(starting|completed) request' ~/.soothe/logs/daemon.log*
```

### 3. cli.log

```bash
rg -i 'websocket|connection|timeout|retry' ~/.soothe/logs/cli.log* | tail -40
rg '"event":"(goal_completed|turn_finished)"' ~/.soothe/logs/cli.log* | tail -20
rg '\[Router\]|\[Step\]' ~/.soothe/logs/cli.log* | tail -40
```

### 4. Cross-correlate

Timeline: **time | source | event**. Flag gaps (last `[7cba]` then silence while
daemon still shows worker busy).

| Symptom | soothe.log | daemon.log | cli.log |
|---------|------------|------------|---------|
| Loop hang | Mid-step; no Step completed/failed | `starting` without `completed` | Spinner may persist |
| Wall-clock cap | Step `cancelled` near deadline | `request timeout` | No `goal_completed` |
| Stream ended | Recoverable tool errors | Worker completes | Late `turn_finished` |
| TUI step count &lt; log | Multiple Plan iterations | — | Overlay mismatch |

## Workflow B — Diagnose a Specific Loop

Primary sources: `runner.log` → `soothe.log` `[suffix]` → `daemon.log` `loop=`.

```bash
LOOP_ID='019f01c8-56e9-73d1-9271-0ca7ba307cba'
SUFFIX="${LOOP_ID: -4}"
LOG=~/.soothe/data/loops/$LOOP_ID/runner.log
```

### B1. Loop timeline

```bash
rg "\[$SUFFIX\].*\[Loop\]|^\d.*\[$SUFFIX\].*Step |^\d.*\[$SUFFIX\].*\[Execute\]" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

| Pattern | Meaning |
|---------|---------|
| `[Loop] Iteration N started` | Iteration boundary |
| `[Loop] Plan: N steps (...)` | Plan emitted |
| `[Execute] steps=N mode=...` | Execute wave |
| `Step {id} completed ... in {ms}ms` | Success + duration |
| `Step {id} failed` / `cancelled` | Failure / interrupt |
| `Tool budget reached` | `max_tool_calls_per_step` |

### B2. Abnormal tool calls

`[Tool#N]` is INFO; `[write_todos]` is DEBUG.

```bash
rg "\[$SUFFIX\].*\[Tool#[0-9]+\].*returned error|^\d.*\[$SUFFIX\].*Step .* failed" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
rg "\[$SUFFIX\].*Tool budget reached|Stream ended unexpectedly|UnicodeDecodeError" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
rg "\[$SUFFIX\].*Step .* (completed|failed).* in [0-9]+ms" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Classify: tool / all-tools-failed / network / budget / subagent.

Flag: `duration_ms > 120_000`; no completion within 5× median; same tool+args
≥ 3×; same tool > 10×/step; A→B→A→B oscillation.

### B3. StrangeLoop plan analysis

```bash
rg "\[$SUFFIX\].*(\[Loop\] Plan:|\[Plan\]|\[PlanGenerate\]|Plan result:|\[PlanGen\] Dropped)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
rg "\[$SUFFIX\].*\[Plan\] phase=" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Waste signals: `plan=new` while steps runnable; over-segmented plans; duplicate
descriptions; TUI done but replanned; dependency mode steps never started;
`[PlanGen] Dropped` fillers.

```bash
soothe loop show "$LOOP_ID"
soothe loop tree "$LOOP_ID"
```

### B4. CoreAgent todos (`write_todos`, DEBUG)

```bash
rg "\[$SUFFIX\].*\[write_todos\]" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Waste: pending while unrelated tools run; repeated identical todos; few
completed; contradict step brief; status flip-flop.

### B5. Skill loading

Flow: index → discover → invoke (body into `SKILL_CONTEXT`).

Roots: builtin skills, `~/.soothe/skills`, `~/.agents/skills`, loop workspace,
`skillify.warehouse_paths`. Later roots win on name collision.

```bash
rg "\[$SUFFIX\].*(\[Skill\]|skill_activation|search_skills|invoke_skill|/skill:|active_skills=)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
rg "\[$SUFFIX\].*(Skill not found|No deferred skills|did not expand|sync failed)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Per expected skill: found in index → discovered → body loaded → used
(`active_skills > 0`). Deferred discovered but never invoked = found, not loaded.

## Output Template (loop)

```markdown
## Loop {suffix} ({full_uuid})

### Summary
Outcome, root cause, severity.

### Timeline
| Time | Component | Event |

### Tool anomalies
Errors / latency / repetition (≥3)

### Plan assessment
Iterations, waste, unexpected failures

### Todo assessment
Snapshots, waste signals

### Skill loading assessment
Expected / found / discovered / loaded / anomalies

### Recommendations
…
```

## Enable Richer Logs

```bash
export SOOTHE_LOG_LEVEL=DEBUG
# config: debug: true; logging.file.level: DEBUG
soothed stop && soothed start
soothe --log-level DEBUG
```

`[write_todos]` / `[Skill]` need DEBUG; `[Tool#N]` is INFO.

## Guardrails

- Idle worker respawn ≠ investigated loop crash — check worker id + loop id.
- `soothe.log` `[suffix]` is last 4 of thread id (usually loop id).
- Prefer `runner.log` for pooled workers.
- Classify infra first: `request_timeout` (default 14d / `1209600`), tool budget,
  missing `rg`/`ag`, checkpoint races.
- Never cite IG-/RFC- ids in user-facing diagnosis text.

## Related

- Autopilot jobs: [inspect-autopilot-job](../inspect-autopilot-job/SKILL.md)
- Debug guide: `docs/wiki/howto_debug.md`
- CLI: `soothe loop list|show|tree|continue`
- Example writeups: `docs/impl/archive/IG-509-loop-7cba-hang-analysis.md`
