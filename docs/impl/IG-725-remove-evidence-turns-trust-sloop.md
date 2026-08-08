# IG-725: Remove evidence turns; trust StrangeLoop completion + Monitor DAG

**Created**: 2026-08-08  
**Status**: Implemented  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-625](../specs/RFC-625-autopilot-monitor.md) (Monitor / DAG verify),
[IG-707](IG-707-autopilot-automatic-consensus-no-operator-suspend.md),
[IG-710](IG-710-consensus-trust-sloop-response.md),
[IG-724](../archive/impl/IG-724-engine-driven-trivial-evidence-turns.md) (archived)

---

## Goal

Remove Autopilot **`collect_evidence`** / `evidence_follow_up` turns. Trust
StrangeLoop Plan-Execute-Eval terminal completion for per-goal accept quality.
After CE marks a goal completed, **AutopilotMonitor** (not a second worker
mission) evaluates ContextEngine DAG status and decides whether to update the
DAG or wait for further goal completions.

---

## Background

IG-724 added a trivial same-loop evidence mission when consensus flagged
missing workspace/git/file proof. In practice (e.g. job `18d59e9d` maker
`45862724`):

1. Implement completed with real worktree commits.
2. Consensus `send_back` + `evidence_follow_up` queued `mission=collect_evidence`.
3. Assess never emitted `done` on the proof brief → dozens of duplicate
   “fresh workspace proof” steps; product progress froze; rail could not
   advance to integrate.

Rejected alternatives (unchanged from IG-724): host FS probes, daemon
`bind_tools` consensus, job-level LangGraph for evidence.

**New rule:** do not re-dispatch the same goal for proof theater. One
implement (or rail-role) dispatch → StrangeLoop completes → host finalize →
Monitor / LoopRail react to CE state.

---

## Design rules (MUST)

1. **No `collect_evidence` mission.** Drop `mission` / `mission_brief` /
   `evidence_round` from `GoalDispatchEnvelope` entirely.
2. **No `evidence_follow_up` on consensus.** Verdict is
   `accept | send_back | fail` only. Prompt must **not** ask for workspace
   proof gaps or prefer send_back solely because the narrative is thin
   relative to git/files on disk.
3. **Trust StrangeLoop done.** Prefer `accept` when Plan-Execute-Eval
   returned a successful completion narrative unless the response clearly
   shows product work incomplete/wrong or fundamentally blocked (`fail`).
   Product `send_back` remains for genuine rework — not proof collection.
4. **Host still does not open the goal workspace** for consensus grounding
   (IG-710). Judge input is the CE-committed Goal Report projection
   (IG-726), not a second workspace probe.
5. **Post-completion ownership:**
   - AutopilotService: `complete_goal` → `INTERNAL_GOAL_COMPLETED` + rail
     `goal_completed` / `dag_idle`.
   - AutopilotMonitor: on completed/failed events + background health —
     evaluate completed/active/failed/pending; apply post-completion /
     health rewires; do **not** spawn evidence worker turns.
6. **Architecture WavePlan gate** (require_plan) stays host-owned and is
   unrelated to evidence missions.
7. **One dispatch per attempt.** Sticky `evidence_prefer_loop_id` and
   `queue_evidence_turn` are removed.

---

## Target flow

```text
CE/rail emits goal → Autopilot dispatch (implement)
  → StrangeLoop Plan-Execute-Eval → GoalCompletionChunk
  → _apply_consensus_and_finalize
        accept → CE.complete_goal → INTERNAL_GOAL_COMPLETED
        send_back → CE.send_back_goal (product rework only)
        fail → CE.fail_goal
  → AutopilotMonitor._on_goal_completed / health loop
        → verify_dag_post_completion / verify_dag_health
        → update DAG or wait for more completions
  → LoopRail on goal_completed / dag_idle (phase builtins)
```

---

## Code touchpoints

| Area | Action |
|------|--------|
| `autopilot/verify/consensus.py` | Drop `evidence_follow_up`; rewrite prompt trust SL |
| `autopilot/service.py` | Remove evidence queue branch, `_evidence_mission_brief`, mission dispatch |
| `context/engine.py` | Remove `queue_evidence_turn` |
| `context/models.py` | Remove evidence mission GoalNode fields |
| `protocols/runner.py` | Simplify `GoalDispatchEnvelope` (no collect_evidence) |
| `runner/_runner_autopilot_worker.py` | Stop branching on collect_evidence |
| Tests | Replace `test_ig724_*` with IG-725 coverage |
| Docs | Supersede IG-724; patch RFC-204/222, wiki, IG-710 |

---

## Acceptance

- [x] Consensus send_back for “missing git proof” does **not** re-dispatch
      `collect_evidence` (product send_back only).
- [x] Accept path emits `INTERNAL_GOAL_COMPLETED` for Monitor.
- [x] No `pending_mission` / `queue_evidence_turn` / `_evidence_mission_brief`.
- [x] Unit tests green; `./scripts/verify_finally.sh` green.
- [x] User-facing strings omit IG-/RFC- identifiers.

---

## Non-goals

- Removing AutopilotMonitor post-completion / health LLM entirely.
- Removing product `send_back` / `fail` consensus.
- Changing LoopRail builtins or WavePlan architecture gate.
