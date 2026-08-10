# Inspect Autopilot Job — Reference Scripts

Helpers for [SKILL.md](SKILL.md). Run with repo `.venv/bin/python` when possible.

## Rail trace: builtins only

```bash
JOB=921c6d32
TRACE=~/.soothe/data/jobs/$JOB/rail_trace.jsonl
test -f "$TRACE" || TRACE=~/.soothe/data/loops/$JOB/rail_trace.jsonl
python3 - "$TRACE" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
for line in p.read_text().splitlines():
    r = json.loads(line)
    if not r.get("builtin"):
        continue
    gr = r.get("guard_result") or {}
    print(
        f"seq={r.get('seq')}\t{r.get('timestamp','')}\t{r.get('event')}\t"
        f"cond={r.get('condition')}\t{r.get('builtin')}={r.get('builtin_result')}\t"
        f"goal={(r.get('goal_id') or '')[:8]}\tmatched={gr.get('matched')}"
    )
    if gr.get("reasoning"):
        print(f"  {str(gr.get('reasoning'))[:160]}")
PY
```

## Rail trace: full dump (noisy — skip pure dag_idle)

```bash
python3 - "$TRACE" <<'PY'
import json, pathlib, sys
from collections import Counter
p = pathlib.Path(sys.argv[1])
ev = Counter()
for line in p.read_text().splitlines():
    r = json.loads(line)
    ev[r.get("event")] += 1
    if r.get("event") == "dag_idle" and not r.get("builtin"):
        continue
    cols = [r.get("seq"), r.get("event"), r.get("condition"), r.get("builtin"),
            r.get("builtin_result"), (r.get("goal_id") or "")[:8]]
    print("\t".join("" if c is None else str(c) for c in cols))
    gr = r.get("guard_result") or {}
    if r.get("condition") and gr:
        print(f"  matched={gr.get('matched')} {str(gr.get('reasoning',''))[:120]}")
print("event_counts", ev.most_common())
PY
```

## job_loops: per-goal attempt ledger

```bash
JOB=921c6d32
python3 - "$JOB" <<'PY'
import json, sqlite3, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

job = sys.argv[1]
conn = sqlite3.connect(str(Path.home() / ".soothe/data/databases/persist.db"))
row = conn.execute(
    "SELECT data FROM soothe_kv WHERE namespace='autopilot_goals' "
    "AND key=?",
    (f"autopilot:job_loops:{job}",),
).fetchone()
if not row:
    raise SystemExit(f"no job_loops for {job}")
data = json.loads(row[0])
print(f"status={data.get('status')} active={data.get('active_loops')} "
      f"next_seq={data.get('next_seq')} n={len(data.get('loops') or [])}")
by = defaultdict(list)
for e in data.get("loops") or []:
    by[e["goal_id"]].append(e)
print(f"{'goal':8} {'n':>2} {'ok':>2} {'fail':>4} {'wall_m':>7} span")
for gid, entries in sorted(by.items(), key=lambda x: min(
    (e.get("started_at") or "") for e in x[1]
)):
    ok = sum(1 for e in entries if e.get("status") == "completed")
    fail = sum(1 for e in entries if e.get("status") == "failed")
    starts = [e["started_at"] for e in entries if e.get("started_at")]
    ends = [e["ended_at"] for e in entries if e.get("ended_at")]
    if starts and ends:
        t0 = datetime.fromisoformat(min(starts).replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(max(ends).replace("Z", "+00:00"))
        wall = (t1 - t0).total_seconds() / 60
        span = f"{min(starts)[11:19]}→{max(ends)[11:19]}"
    else:
        wall, span = 0.0, "?"
    print(f"{gid[:8]:8} {len(entries):2} {ok:2} {fail:4} {wall:7.1f} {span}")
PY
```

## CE snapshot: job subtree + depends_on

```bash
JOB=921c6d32
python3 - "$JOB" <<'PY'
import json, sqlite3, sys
from pathlib import Path

job = sys.argv[1]
conn = sqlite3.connect(str(Path.home() / ".soothe/data/databases/persist.db"))
row = conn.execute(
    "SELECT data FROM soothe_kv WHERE namespace='autopilot_goals' "
    "AND key='autopilot:goals:snapshot'"
).fetchone()
data = json.loads(row[0])
goals = {g["id"]: g for g in data["goals"]}

def root_of(gid):
    seen = set()
    cur = goals.get(gid)
    while cur and cur.get("parent_id") and cur["id"] not in seen:
        seen.add(cur["id"])
        cur = goals.get(cur["parent_id"])
    return cur["id"] if cur else None

job_goals = [g for g in data["goals"] if g["id"] == job or root_of(g["id"]) == job]
print(f"n={len(job_goals)}")
print(f"{'id':8} {'status':10} {'pri':>3} {'role':10} "
      f"{'r/sb/erc':>10} deps  description")
for g in sorted(job_goals, key=lambda x: (x.get("parent_id") or "", x["id"])):
    deps = ",".join((g.get("depends_on") or [])[:4])
    budget = f"{g.get('retry_count',0)}/{g.get('send_back_count',0)}/{g.get('engine_recovery_count',0)}"
    print(f"{g['id'][:8]:8} {g['status']:10} {g.get('priority',0):3} "
          f"{(g.get('role') or ''):10} {budget:>10} {deps:28} "
          f"{(g.get('description') or '')[:50]}")
print("--- edges ---")
for g in job_goals:
    for d in g.get("depends_on") or []:
        st = goals.get(d, {}).get("status", "?")
        print(f"  {g['id'][:8]} → {d[:8]} ({st})")
PY
```

## CE goal DAG: analysis + digraph

Parses the live snapshot, restricts to the job subtree (root == `JOB` or
`parent_id` chain back to `JOB`, plus orphans whose root was this job), then
runs the Context Engine goal DAG analysis the skill reports:

- **Topology**: topo layers (rank from roots), fan-out, leaves.
- **Cycles**: any edge into a node on its ancestor path (would deadlock the CE
  scheduler and never reach terminal).
- **Orphans / unreachable**: goals with no path to `JOB` root (stale DAG
  clutter from pruned branches or rewritten parents).
- **Root-wiring violations** (skill §1 checks): child `depends_on` the active
  job root (deadlock while root active); root `depends_on` a non-terminal
  child (inverted gate).
- **Ready / blocked**: pending goals whose `depends_on` are all terminal
  (ready, prefer completed) vs pending with unmet deps (blocked, list blockers
  and their status).
- **Critical path**: longest dependency chain of uncompleted goals →
  min steps to job completion (lower bound on remaining serial work).
- **Digraph**: Graphviz **DOT** with status-colored nodes, role/rail labels,
  and `depends_on` edges. Also a mermaid `graph LR` and an ASCII tree
  fallback for terminals without Graphviz.

```bash
JOB=921c6d32
python3 - "$JOB" <<'PY'
import json, sqlite3, sys
from pathlib import Path

JOB = sys.argv[1]
conn = sqlite3.connect(str(Path.home() / ".soothe/data/databases/persist.db"))
row = conn.execute(
    "SELECT data FROM soothe_kv WHERE namespace='autopilot_goals' "
    "AND key='autopilot:goals:snapshot'"
).fetchone()
if not row:
    raise SystemExit("no goals:snapshot (is the daemon up? run `soothe autopilot job $JOB`)")
data = json.loads(row[0])
goals = {g["id"]: g for g in data["goals"]}

TERMINAL = {"completed", "failed", "cancelled"}
BLOCKED = {"awaiting_clarification", "suspended"}

def root_of(gid):
    seen, cur = set(), goals.get(gid)
    while cur and cur.get("parent_id") and cur["id"] not in seen:
        seen.add(cur["id"])
        cur = goals.get(cur["parent_id"])
    return cur["id"] if cur else None

job_goals = [g for g in data["goals"] if g["id"] == JOB or root_of(g["id"]) == JOB]
ids = {g["id"] for g in job_goals}
sub = {gid: goals[gid] for gid in ids if gid in goals}

# Strict depends_on within subtree (drops deps pointing outside the job).
deps = {gid: [d for d in (sub[gid].get("depends_on") or []) if d in sub] for gid in sub}
dependents = {gid: [d for d, dd in deps.items() if gid in dd] for gid in sub}

# --- Topology: Kahn's algorithm for layered ranks (ignores back-edges) ---
indeg = {gid: 0 for gid in sub}
for gid, dd in deps.items():
    for d in dd:
        indeg[gid] += 1
layer = {gid: 0 for gid in sub}
queue = [gid for gid, d in indeg.items() if d == 0]
processed = 0
while queue:
    nxt = []
    for gid in queue:
        processed += 1
        for child in dependents[gid]:
            indeg[child] -= 1
            layer[child] = max(layer[child], layer[gid] + 1)
            if indeg[child] == 0:
                nxt.append(child)
    queue = nxt
layers = {}
for gid, r in layer.items():
    layers.setdefault(r, []).append(gid)

# --- Cycle detection (DFS ancestor stack) ---
WHITE, GRAY, BLACK = 0, 1, 2
color = {gid: WHITE for gid in sub}
cycles = []
def dfs(gid, stack):
    color[gid] = GRAY
    stack.append(gid)
    for d in deps[gid]:
        if color[d] == GRAY:
            cycles.append(stack[stack.index(d):] + [d])
        elif color[d] == WHITE:
            dfs(d, stack)
    stack.pop()
    color[gid] = BLACK
for gid in sub:
    if color[gid] == WHITE:
        dfs(gid, [])

# --- Orphans: no path to JOB root (ignore self) ---
def reaches_root(gid):
    seen = set()
    stack = [gid]
    while stack:
        x = stack.pop()
        if x == JOB:
            return True
        if x in seen:
            continue
        seen.add(x)
        stack.extend(deps.get(x, []))
        p = sub[x].get("parent_id")
        if p in sub:
            stack.append(p)
    return False
orphans = [gid for gid in sub if gid != JOB and not reaches_root(gid)]

# --- Root-wiring violations ---
root = sub.get(JOB)
root_violations = []
if root:
    for gid, dd in deps.items():
        if gid != JOB and JOB in dd and sub[gid]["status"] not in TERMINAL:
            root_violations.append(f"{gid[:8]} depends_on root {JOB[:8]} while root active")
    for d in deps.get(JOB, []):
        if d in sub and sub[d]["status"] not in TERMINAL:
            root_violations.append(f"root {JOB[:8]} depends_on {d[:8]} (non-terminal child)")

# --- Ready / blocked ---
ready, blocked = [], []
for gid, g in sub.items():
    if g["status"] != "pending":
        continue
    unmet = [d for d in deps[gid] if sub.get(d, {}).get("status") not in TERMINAL]
    if unmet:
        why = ", ".join(f"{d[:8]}({sub[d]['status']})" for d in unmet)
        blocked.append((gid, why))
    else:
        ready.append(gid)

# --- Critical path (longest uncompleted dependency chain) ---
def chain_len(gid, seen):
    if gid in seen:
        return 0
    seen.add(gid)
    if sub[gid]["status"] in TERMINAL or not deps[gid]:
        return 1
    return 1 + max((chain_len(d, seen.copy()) for d in deps[gid]), default=0)
cp = sorted(((chain_len(gid, set()), gid) for gid in sub
             if sub[gid]["status"] not in TERMINAL), reverse=True)

# --- Status style colors (match _STATUS_STYLE in autopilot_cmd.py) ---
DOT_STYLE = {
    "active": 'fillcolor="#00ff5f", fontcolor=black',
    "pending": 'fillcolor="#ffff00", fontcolor=black',
    "completed": 'fillcolor="#008000", fontcolor=white',
    "failed": 'fillcolor="#ff0000", fontcolor=white',
    "cancelled": 'fillcolor="#8b0000", fontcolor=white',
    "suspended": 'fillcolor="#ffd700", fontcolor=black',
    "blocked": 'fillcolor="#ffd700", fontcolor=black',
    "awaiting_clarification": 'fillcolor="#ffd700", fontcolor=black',
}

print(f"=== CE goal DAG analysis: job {JOB[:8]} ===")
print(f"goals={len(sub)} layers={len(layers)} "
      f"cycles={len(cycles)} orphans={len(orphans)} "
      f"root_violations={len(root_violations)} "
      f"ready={len(ready)} blocked={len(blocked)}")
for r in sorted(layers):
    gids = ", ".join(g[:8] for g in sorted(layers[r]))
    print(f"  L{r} ({len(layers[r])}): {gids}")
if cycles:
    print("--- cycles (deadlock) ---")
    for c in cycles:
        print("  " + " -> ".join(x[:8] for x in c))
if orphans:
    print("--- orphans (stale DAG clutter) ---")
    for o in sorted(orphans):
        print(f"  {o[:8]} status={sub[o]['status']} "
              f"parent={(sub[o].get('parent_id') or '')[:8]}")
if root_violations:
    print("--- root-wiring violations ---")
    for v in root_violations:
        print(f"  {v}")
if ready:
    print("--- ready (pending, all deps terminal) ---")
    for gid in ready:
        print(f"  {gid[:8]} pri={sub[gid].get('priority',0)} "
              f"role={sub[gid].get('role') or '-'}")
if blocked:
    print("--- blocked (pending, unmet deps) ---")
    for gid, why in blocked:
        print(f"  {gid[:8]} blocked_by: {why}")
if cp:
    print("--- critical path (longest uncompleted chain) ---")
    for length, gid in cp[:5]:
        print(f"  {gid[:8]} depth={length} status={sub[gid]['status']}")

print("\n=== DOT digraph ===")
print(f'digraph "{JOB[:8]} goal DAG" {{')
print("  rankdir=LR; node [shape=box, style=filled];")
for gid, g in sub.items():
    st = g.get("status", "pending")
    style = DOT_STYLE.get(st, 'fillcolor=white')
    role = g.get("role") or "-"
    desc = (g.get("description") or "")[:40].replace('"', "'")
    rail = g.get("rail_id") or ""
    label = f"{gid[:8]}\\n{st}\\nrole:{role}" + (f"\\nrail:{rail}" if rail else "") + f"\\n{desc}"
    print(f'  "{gid}" [label="{label}", {style}];')
for gid, dd in deps.items():
    for d in dd:
        ds = sub.get(d, {}).get("status", "?")
        col = "green" if ds == "completed" else ("red" if ds == "failed" else "black")
        print(f'  "{gid}" -> "{d}" [color={col}];')
print("}")

print("\n=== mermaid graph LR ===")
print("```mermaid")
print("graph LR")
for gid, g in sub.items():
    st = g.get("status", "pending")
    role = g.get("role") or "-"
    print(f'  {gid[:8]}(["{gid[:8]}<br/>{st}<br/>role:{role}"])')
for gid, dd in deps.items():
    for d in dd:
        print(f"  {gid[:8]} --> {d[:8]}")
print("```")

print("\n=== ASCII tree ===")
children = {gid: [] for gid in sub}
for gid, dd in deps.items():
    for d in dd:
        children.setdefault(d, []).append(gid)
def render(gid, indent="", last=True):
    g = sub.get(gid, {})
    st = g.get("status", "?")
    print(f'{indent}{"└─ " if last and indent else ("" if not indent else "├─ ")}'
          f'{gid[:8]} ({st}) role:{g.get("role") or "-"}')
    kids = sorted(children.get(gid, []))
    for i, c in enumerate(kids):
        render(c, indent + ("    " if last else "│   "), i == len(kids) - 1)
render(JOB)
PY
```

Feed the DOT block to Graphviz for a rendered diagram. The analysis script
above prints the full DOT block between a `=== DOT digraph ===` header and
the next `===` section; slice it with `sed` and pipe to `dot`:

```bash
# Save the analysis script above as dag_analyze.py, then:
python3 dag_analyze.py "$JOB" | sed -n '/^digraph "/,/^}$/p' \
  | dot -Tsvg > /tmp/job_dag.svg && open /tmp/job_dag.svg
# inline terminal layout:  ... | dot -Tplain
```

When `dot` is absent, use the **mermaid** block (render in any mermaid viewer)
or the **ASCII tree** printed inline.

## rail_state annotations

```bash
python3 - <<'PY'
import json
from pathlib import Path
JOB = "921c6d32"
s = json.loads(Path.home().joinpath(f".soothe/data/jobs/{JOB}/rail_state.json").read_text())
for k in ("rail_id", "wave_index", "max_waves", "feedback_round",
          "max_feedback_rounds", "acceptance_met", "worktrees_enabled"):
    print(f"{k}: {s.get(k)}")
for gid, a in sorted((s.get("annotations") or {}).items()):
    print(f"  {gid}: role={a.get('role')} tags={a.get('tags')} "
          f"branch={a.get('branch_id')} status={a.get('branch_status')}")
PY
```
