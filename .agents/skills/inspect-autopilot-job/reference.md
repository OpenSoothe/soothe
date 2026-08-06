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
