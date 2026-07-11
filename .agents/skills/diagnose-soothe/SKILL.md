---
name: diagnose-soothe
description: >-
  Diagnose Soothe agent loops from ~/.soothe/logs (soothe.log, daemon.log,
  cli.log) and per-loop runner.log. Analyzes StrangeLoop plans, CoreAgent
  write_todos, tool-call anomalies (errors, latency, repetition), step
  failures, and progressive skill loading (discovery, intent prefetch,
  invoke_skill, /skill: expansion). Use when debugging loop hangs, failed
  steps, TUI/daemon mismatches, abnormal tool usage, wasteful plans/todos,
  skills not found or not loaded, or when the user asks to analyze soothe
  logs or diagnose a specific loop.
---

# Diagnose Soothe

Systematic log forensics for Soothe loops, daemon lifecycle, and CLI/TUI behavior.

## When to Use

- User reports a loop hang, failed step, spinner stuck, or missing TUI progress
- User asks to analyze `~/.soothe/logs/` or a specific loop (by UUID or 4-char suffix)
- User wants root-cause analysis of tool errors, slow steps, or repetitive tool calls
- User asks whether a StrangeLoop plan or CoreAgent todo list has waste or failed steps
- User reports a skill did not load, `/skill:name` failed, or agent ignored skill instructions

## Log Locations

| File | Logger / purpose | Loop correlation |
|------|------------------|------------------|
| `~/.soothe/logs/soothe.log` | `soothe.*`, `soothe_plugins.*` — StrangeLoop, CoreAgent, tools, planner | 4-char suffix tag: `[7cba]` (last 4 chars of loop/thread id) |
| `~/.soothe/logs/daemon.log` | `soothe_daemon.*` — WebSocket, workers, loop_new/input, thread pool | Full UUID in prefix: `[loop=019f01c8-56e9-73d1-9271-0ca7ba307cba]` |
| `~/.soothe/logs/cli.log` | `soothe_cli.*` — connection, event routing, structured turn stats | JSON events may include loop context; grep loop id suffix |
| `~/.soothe/data/loops/{loop_id}/runner.log` | Same format as `soothe.log`, scoped to one loop (worker pool / subprocess) | Always that loop; prefer when central log is noisy |

Rotated backups: `*.log.1`, `*.log.2`, etc. Search all when the incident is older than the current file.

**Note:** Some docs say `soothed.log` or `soothe-cli.log`; runtime defaults are `daemon.log` and `cli.log`.

## Resolve Loop Identity

User may give a full UUID, 4-char suffix (`7cba`, `3328`), or step id prefix (`UZH-01`).

1. **List loops** (daemon must be running):
   ```bash
   soothe loop list
   ```
2. **Match suffix** in data dir:
   ```bash
   ls ~/.soothe/data/loops/ | grep -i '<suffix>'
   ```
3. **Find in soothe.log**:
   ```bash
   rg '\[<suffix>\]' ~/.soothe/logs/soothe.log*
   ```
4. **Find in daemon.log**:
   ```bash
   rg 'loop=.*<suffix>' ~/.soothe/logs/daemon.log*
   ```

Record: full `loop_id`, time range (first/last log line), worker id if present (`thread-worker-0`), goal index if multi-goal.

## Workflow A — Broad Log Triage (loops + daemon + CLI)

Run in parallel, then correlate timestamps.

### 1. soothe.log — agent execution

```bash
# Errors and failures
rg -i 'error|exception|failed|Traceback' ~/.soothe/logs/soothe.log* | tail -80

# Active loops (recent tags)
rg '^\d{4}-\d{2}-\d{2}.*\[[0-9a-f]{4}\]' ~/.soothe/logs/soothe.log* | tail -30

# Planner / iteration
rg '\[Loop\]|\[Plan\]|\[Execute\]|\[LLMPlanner\]' ~/.soothe/logs/soothe.log* | tail -50
```

### 2. daemon.log — transport & workers

```bash
# Loop lifecycle
rg 'loop_new|loop_input|thread-worker|completed request|Worker thread exited' ~/.soothe/logs/daemon.log* | tail -80

# Errors
rg -i 'error|exception|failed|timeout' ~/.soothe/logs/daemon.log* | tail -50

# Stuck worker pattern: "starting request" without matching "completed request"
rg 'thread-worker.*(starting|completed) request' ~/.soothe/logs/daemon.log*
```

### 3. cli.log — client & TUI

```bash
# Connection / WebSocket
rg -i 'websocket|connection|timeout|retry' ~/.soothe/logs/cli.log* | tail -40

# Structured turn events (JSON lines)
rg '"event":"(goal_completed|turn_finished)"' ~/.soothe/logs/cli.log* | tail -20

# Routing / step cards (DEBUG)
rg '\[Router\]|\[Step\]' ~/.soothe/logs/cli.log* | tail -40
```

### 4. Cross-correlate

Build a timeline table: **time | source | event**. Flag gaps (e.g. last `[7cba]` line then silence while daemon still shows worker busy).

Common cross-log patterns:

| Symptom | soothe.log | daemon.log | cli.log |
|---------|------------|--------------|---------|
| Loop hang | Last line mid-step; no `Step X completed/failed` | `starting request` never `completed request` | Events stop; spinner may persist |
| Goal failed at wall-clock cap | Step `cancelled` near deadline | `request timeout (1209600s)` or `Request exceeded … timeout` | Frozen snapshot; no `goal_completed` |
| Stream ended unexpectedly | Step failed / recoverable tool errors | Worker completes | `turn_finished` may still arrive late |
| TUI step count < log steps | Multiple `[Loop] Plan:` / iterations | — | Plan overlay vs execute events mismatch |
| Second goal never starts | Goal completion logs | `done` before worker `ready` | No new events after input |

## Workflow B — Diagnose a Specific Loop

Primary sources (in order):

1. `~/.soothe/data/loops/{loop_id}/runner.log` (if exists)
2. `rg '\[{suffix}\]' ~/.soothe/logs/soothe.log*`
3. `rg 'loop={loop_id}' ~/.soothe/logs/daemon.log*`

Extract `LOOP_SUFFIX` (last 4 chars) and set:

```bash
LOOP_ID='019f01c8-56e9-73d1-9271-0ca7ba307cba'   # example
SUFFIX="${LOOP_ID: -4}"
LOG=~/.soothe/data/loops/$LOOP_ID/runner.log
# fallback: rg -n "\[$SUFFIX\]" ~/.soothe/logs/soothe.log*
```

### B1. Loop timeline

```bash
rg "\[$SUFFIX\].*\[Loop\]|^\d.*\[$SUFFIX\].*Step |^\d.*\[$SUFFIX\].*\[Execute\]" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Key lines:

| Pattern | Meaning |
|---------|---------|
| `[Loop] Iteration N started` | StrangeLoop iteration boundary |
| `[Loop] Plan: N steps (MODE mode, cumulative: T total, D done)` | Plan emitted to client |
| `[Execute] steps=N mode=...` | Execute wave sizing |
| `Step {id} completed successfully in {ms}ms (...)` | Step success + duration + tool counts |
| `Step {id} failed: ...` / `failed after {ms}ms` | Step failure |
| `Step {id} cancelled after {ms}ms` | Cancel / interrupt |
| `Tool budget reached` | Hit `max_tool_calls_per_step` |

### B2. Abnormal tool calls

Requires **DEBUG** level in soothe/runner logs for full `[Tool#N]` lines. At INFO, still catch warnings/errors.

#### Errors

```bash
rg "\[$SUFFIX\].*\[Tool#[0-9]+\].*returned error|^\d.*\[$SUFFIX\].*Step .* failed" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
rg "\[$SUFFIX\].*Tool budget reached|Stream ended unexpectedly|UnicodeDecodeError|ValueError" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Classify each error: **tool** (single call), **all tools failed** (step), **network/stream**, **policy/budget**, **subagent delegate**.

#### Long latency

Parse step completion lines for `in {ms}ms`. Flag steps where:

- `duration_ms > 120_000` (2 min) — investigate tool/subagent breakdown
- Step started (execute / step id in logs) with no completion within 5× median step time

For DEBUG tool timing, count tools per step and note last `[Tool#N]` before silence (hang indicator).

```bash
rg "\[$SUFFIX\].*Step .* (completed|failed).* in [0-9]+ms" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

#### Repetitive calls (same tool + same args)

From DEBUG lines:

```
[Tool#N] {name}({id}) args={...} → {type}, {bytes}B
```

Analysis steps:

1. Extract all `[Tool#N]` lines for the loop (and per step if `step=` available).
2. Normalize args JSON (ignore whitespace); group by `(step_id, tool_name, args_hash)`.
3. Flag groups with **count ≥ 3** — likely retry loop, no-progress search, or missing cache.
4. Cross-check `write_todos`: repeated `grep`/`read_file`/`glob` on identical paths without todo status change → execution waste.

Also flag:

- Same tool name **> 10× in one step** without subagent delegation
- Alternating pair pattern (A→B→A→B) — oscillation

### B3. StrangeLoop plan analysis

Collect all plan-related lines:

```bash
rg "\[$SUFFIX\].*(\[Loop\] Plan:|\[Plan\]|\[PlanGenerate\]|\[LLMPlanner\]|Plan result:|\[PlanGen\] Dropped)" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

For each iteration, record:

- Step ids and descriptions (from `[Loop] Plan:` event payload in logs or `soothe loop show {loop_id}` if daemon up)
- `execution_mode` (`parallel` / `dependency`)
- `plan_action` (`new` / `keep`) from `Plan result: status=... plan=...`
- `[PlanGen] Dropped N filler step(s)` — planner already removed noise

**Waste / redundancy checks:**

| Signal | Interpretation |
|--------|----------------|
| Plan regenerated (`plan=new`) while steps still runnable | Possible thrashing; check `[Plan] Reject` / stuck detection |
| Many steps, few tool calls each | Over-segmented plan |
| Duplicate descriptions across iterations | Replan without progress |
| Steps marked done in TUI but replanned | Checkpoint / display snapshot mismatch (see daemon goal snapshots) |
| `[Execute] dependency mode finished with N/M step(s) never started` | DAG deps blocked or failed predecessors |
| Filler dropped by `[PlanGen]` | Confirms low-value steps in raw LLM output |

**Unexpected step failures:**

- Map each `Step {id} failed` to plan step description
- Note `success=False` with recoverable tool errors vs hard failure
- Check prior step outputs: missing predecessor evidence often causes downstream failure
- Compare failed step tool count vs `main_tools` / `subgraph_tools` in completion line

Optional (daemon running):

```bash
soothe loop show "$LOOP_ID"
soothe loop tree "$LOOP_ID"    # checkpoint branches / failed paths
```

### B4. CoreAgent todo list (`write_todos`)

DEBUG only:

```bash
rg "\[$SUFFIX\].*\[write_todos\]" "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Each block lists numbered todos: `{n}. [{status}] {content}`.

**Waste / hygiene checks:**

| Signal | Interpretation |
|--------|----------------|
| Todos stay `pending` while tools run unrelated work | Plan drift; agent not driving todos |
| Same todo content repeated across writes | Todo theater without progress |
| Many todos, few marked `completed` at step end | Over-planning inside step |
| Todos contradict StrangeLoop step brief | Scope creep within CoreAgent |
| Flip-flop status (`pending`→`completed`→`pending`) | Unstable execution |

Correlate todo snapshots with tool calls **between** consecutive `[write_todos]` lines for the same step.

### B5. Skill loading (discovery → activation → body load)

Progressive skills flow: **index** (daemon scan) → **discover** (search, path, intent prefetch, `/skill:`) → **invoke** (body into `SKILL_CONTEXT`). For a specific loop, verify each expected skill was **found** and **loaded** (body present in activation state).

#### Skill index roots (host-level, affects all loops)

| Root | Label | Notes |
|------|-------|-------|
| `packages/soothe/.../builtin_skills/` | `builtin` | Shipped with Soothe |
| `~/.soothe/skills` | `user` | User-installed skills |
| `~/.agents/skills` | `user` | Community / Cursor-style skills |
| Loop workspace | runtime | Project-local skills; resolved per loop |
| `skillify.warehouse_paths` | Skillify | Semantic index only; defaults prepend the two user roots |

Later roots win on name collision (`~/.agents/skills` > `~/.soothe/skills` > built-ins).

#### Loop skill log grep

```bash
# All skill-related lines for this loop
rg "\[$SUFFIX\].*(\[Skill\]|\[StrangeLoop\].*skill|skill_activation|search_skills|invoke_skill|/skill:|active_skills=)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null

# Failures and misses
rg "\[$SUFFIX\].*(Skill not found|No deferred skills|did not expand|sync failed|\[Skill\].*failed)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null

# Tool-based discovery/load (DEBUG)
rg "\[$SUFFIX\].*\[Tool#[0-9]+\].*(search_skills|invoke_skill)" \
  "$LOG" ~/.soothe/logs/soothe.log* 2>/dev/null
```

Daemon / host infrastructure (not loop-tagged; check around loop start time):

```bash
rg "Warehouse path does not exist|Skillify index ready|Failed to parse.*SKILL\.md|\[Middleware\] Skill activation enabled|\[Init\] Progressive search_skills" \
  ~/.soothe/logs/soothe.log* ~/.soothe/logs/daemon.log* 2>/dev/null | tail -30
```

#### Log patterns → meaning

| Pattern | Level | Meaning |
|---------|-------|---------|
| `[StrangeLoop] /skill: user line did not expand` | W | `/skill:name` submitted but skill missing or unreadable `SKILL.md` on this host |
| `[Skill] core intent auto-invoked ['x']` | D | Turn-0 prefetch matched core tier; body preloaded into `SKILL_CONTEXT` |
| `[Skill] intent prefetch discovered deferred ['x']` | D | Deferred skill metadata discovered only — body not loaded until `invoke_skill` |
| `[Tool#N] search_skills(...)` | D | Agent searched deferred catalog |
| `[Tool#N] invoke_skill(...)` | D | Agent requested full skill body load |
| Tool result `Skill not found: 'x'` | — | Name not in catalog (typo, wrong host, or workspace skill not synced) |
| Tool result `No deferred skills matched query=...` | — | Search returned nothing (query too narrow, already activated, or index empty) |
| Tool result `Loaded skill 'x'` | — | Body loaded; should appear in `SKILL_CONTEXT` on next hop |
| Tool result `Discovered N skill(s)` | — | Metadata only; still needs `invoke_skill` unless auto-invoke fired |
| `Skill instructions are already loaded in SKILL_CONTEXT` | — | Redundant `search_skills`/`search_tools` blocked — skill already active |
| `[Skill] sync failed for x` | E | Path activation found skill but workspace mirror failed |
| `Mirrored skill x: ...` | D | Path-triggered skill synced into loop workspace |
| `active_skills=N` (veritas / execute) | D | `N` activated skill names on that execute hop |
| `Warehouse path does not exist: ...` | D | Skillify warehouse dir missing (index gap; substring search may still work) |
| `Skillify index ready (total=N)` | I | Semantic search backend ready with `N` skills |

#### Correctness checklist (per expected skill)

For each skill the user/task implies (e.g. `/skill:github`, intent match, or explicit `invoke_skill`):

1. **Found in index** — skill name appears in catalog for this workspace.
   - Daemon running: TUI `/skills` or daemon `skills_list` RPC returns the name.
   - Offline: `ls ~/.agents/skills/<name>/SKILL.md` or `~/.soothe/skills/<name>/SKILL.md`; check `~/.soothe/cache/skill_index.json`.
2. **Discovered for thread** — one of: `/skill:` expanded (no warning), `[Skill] core intent auto-invoked`, `[Skill] intent prefetch discovered deferred`, `search_skills` hit, or path activation via file op on skill `paths:` patterns.
3. **Body loaded** — one of: `[Skill] core intent auto-invoked`, `invoke_skill` → `Loaded skill`, or `/skill:` expansion (slash body seeded via executor). Deferred skills discovered but never invoked = **found, not loaded**.
4. **Used in execution** — `active_skills > 0` on execute hops, or agent follows skill-specific tools/commands after load. Zero `active_skills` with loaded bodies may mean snapshot not propagated or step ran before invoke.

#### Common failure modes

| Symptom | Likely cause |
|---------|----------------|
| `/skill:x` warning, raw line in planner | Skill dir missing, bad `SKILL.md` frontmatter, or name typo |
| `search_skills` + `Skill not found` on invoke | Discovered name ≠ resolvable dir; workspace skill not under scanned roots |
| Intent prefetch silent, no `[Skill]` lines | `intent_prefetch_enabled: false`, goal shorter than `intent_prefetch_min_query_chars`, or no corpus match |
| Wrong skill auto-invoked | `core_intent_auto_invoke_enabled` matched unintended core skill; check `progressive_skills.core_skills` |
| Repeated `search_skills` / `invoke_skill` | Model rediscovering; prior load lost (checkpoint without `skill_activation` bridge) or invoke failed |
| Skill on laptop, missing in daemon pool | Worker host lacks `~/.agents/skills` install; index differs per machine |
| `Warehouse path does not exist` only | Harmless if user skills live under `~/.agents/skills`; Skillify semantic search degraded |

#### Config knobs (in `~/.soothe/config/config.yml`)

- `progressive_skills.search_skills_enabled` — registers `search_skills` / `invoke_skill` tools
- `progressive_skills.intent_prefetch_enabled` — turn-0 corpus match
- `progressive_skills.core_intent_auto_invoke_enabled` — auto-load matched core bodies
- `progressive_skills.core_skills` — explicit core tier list (`null` = frontmatter `core: true`)
- `skillify.enabled` / `warehouse_paths` — semantic supplement for `search_skills`

## Output Template

Deliver findings in this structure:

```markdown
## Loop {suffix} ({full_uuid})

### Summary
One paragraph: outcome (hang / failed / slow / ok-with-waste), primary root cause, severity.

### Timeline
| Time | Component | Event |
|------|-----------|-------|

### Tool anomalies
- Errors: (count, top types, exemplar lines)
- Latency: (slowest steps, last activity before hang)
- Repetition: (tool+args groups with count ≥ 3)

### Plan assessment
- Iterations / plans: ...
- Wasted or redundant steps: ...
- Unexpected failures: (step id → error → likely cause)

### Todo assessment
- Snapshots reviewed: ...
- Waste signals: ...

### Skill loading assessment
- Expected skills: ...
- Found in index: (yes/no per skill, catalog source)
- Discovery path: (`/skill:`, intent prefetch, `search_skills`, path activation)
- Body loaded: (yes/no; which log line proves it)
- Anomalies: (not found, discovered-but-not-invoked, wrong skill, redundant search, sync failures)

### Recommendations
Actionable fixes (config, prompt, tool install, daemon restart, code bug reference if known).
```

## Enable Richer Logs (if forensics insufficient)

```bash
export SOOTHE_LOG_LEVEL=DEBUG
# In ~/.soothe/config/config.yml: debug: true; logging.file.level: DEBUG
soothed stop && soothed start
soothe --log-level DEBUG
```

Reproduce minimally, then re-run Workflow B. `[Tool#N]`, `[write_todos]`, and `[Skill]` lines require DEBUG.

## Guardrails

- Do not treat idle worker respawn (`thread-worker-1 idle timeout`) as the investigated loop crashing — verify worker id and loop id on each line.
- `soothe.log` `[suffix]` is last 4 chars of thread id; for loops, thread id is typically the loop id.
- Prefer `runner.log` for pooled workers — it avoids cross-loop noise.
- Classify before blaming the model: thread-pool `request_timeout` (default **14d** / `1209600`; `0` = no cap), tool budget, missing `rg`/`ag`, and checkpoint races are common infra causes.
- Never cite internal IG/RFC ids in user-facing diagnosis text.

## Related

- Project debug guide: `docs/wiki/howto_debug.md`
- CLI loop commands: `soothe loop list|show|tree|continue`
- Example incident writeups: `docs/impl/archive/IG-509-loop-7cba-hang-analysis.md`, `docs/impl/IG-549-loop-worker-goal-boundary-hardening.md`
