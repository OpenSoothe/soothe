# IG-724: Engine-driven trivial evidence turns (same-loop tools)

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md),
[RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md),
[IG-710](IG-710-consensus-trust-sloop-response.md),
[IG-707](IG-707-autopilot-automatic-consensus-no-operator-suspend.md)

---

## Goal

Close the gap where makers leave real commits / completion reports on disk
but per-goal consensus send_backs for “thin evidence.” Autopilot must
**request** workspace-scoped tool work through StrangeLoop — not probe the
filesystem in the host, and not grow a second tool agent in the daemon.

When consensus needs proof (branch isolation, `git log`, completion report,
key paths), Autopilot dispatches a **trivial** follow-up turn on the **same
goal worker loop** and **same goal workspace**, forced with
`intake_scope=trivial`. StrangeLoop runs CoreAgent tools; the host consensus
LLM stays structured judgment only.

Broader rule: the Autopilot engine drives **all** agentic tool work via
StrangeLoop dispatches. Host owns DAG, rail, pool, and accept/send_back/fail.

---

## Background

Observed on greenfield Wave‑1 makers: worktrees had substantial commits and
on-disk completion reports, while consensus only saw thin
`evidence_summary` (step/line digests). Root causes:

1. **IG-710** — consensus compares goal text vs StrangeLoop wire response
   only; host must not FS-probe.
2. Wire packing prefers thin `evidence_summary` over richer `full_output`
   (`synthesize_sloop_response`).
3. Agents sometimes mark `goal_done` before citing git/files in the
   completion narrative.

Rejected alternatives:

- **Host consensus `bind_tools`** — second agent runtime in the daemon;
  duplicates CoreAgent tools.
- **Job-level LangGraph** for wave-plan/evidence — recreates LoopRail + CE
  scheduling; stacks a third checkpoint namespace on top of StrangeLoop and
  CoreAgent (RFC-220).
- **Complex send_back re-implement** as the only recovery — burns budget
  rewriting product code when only proof is missing.

---

## Design rules (MUST)

1. **Engine pushes; StrangeLoop tools.** Autopilot never opens the goal
   workspace for consensus grounding. Tool reads happen only inside a
   dispatched StrangeLoop (RFC-222 job contract).
2. **Evidence = trivial same-loop turn.** When the implement completion is
   thin or consensus would send_back for missing proof, Autopilot issues a
   follow-up `LoopRunRequest` with:
   - sticky worker preference (`prefer` last assignment loop when idle),
   - same `goal_id` and `client_workspace` (maker worktree),
   - `intake_scope="trivial"` (skips Pass 1+2; fresh trivial → 1-step
     execute — RFC-630 / client `intake_scope`),
   - short evidence brief as the turn goal text (not the full maker
     description),
   - StrangeLoop iteration budget from `agent.loop.max_iterations` (no
     Autopilot-specific evidence iteration knob).
3. **Implement stays complex.** The original maker/architecture dispatch
   must **not** force `trivial` (would collapse multi-step work to a
   1-step plan).
4. **Consensus remains structured-only.** After implement (+ optional
   evidence) chunks, `evaluate_goal_completion` judges goal text vs
   StrangeLoop response(s). No host file tools on the judge. Either
   implement narrative **or** evidence-turn narrative may substantiate
   accept when together they prove the goal.
5. **No job-lifecycle LangGraph.** LoopRail YAML + CE GoalDAG remain the
   job machine. StrangeLoop remains the per-goal Plan-Execute-Eval graph.
6. **Fresh-trivial routing.** Evidence turns run after the prior
   `GoalCompletionChunk` left the loop idle, so intake hits **fresh**
   trivial inject (not continuation `plan_assess` overlay) unless a
   documented resume path is required.
7. **Budget.** At most **one** `collect_evidence` turn per goal
   (`evidence_turn_count`), distinct from `max_send_backs`. No
   AutopilotConfig knobs. A second proof-gap after the evidence turn falls
   through to normal send_back / fail.
8. **Mission clarity.** Evidence brief MUST instruct: do not modify
   product code; gather proof (branch, commits, completion report paths,
   deliverable map) into the completion narrative / `evidence_summary`.
9. **IG-710 relationship.** Host still must not hard-accept on markers /
   pytest / silent FS append. IG-710’s “no host workspace probes” remains
   for **daemon-local** probes; this IG adds **StrangeLoop-mediated**
   evidence missions as the allowed way to obtain file/git proof.

---

## Flow

```text
dispatch mission=implement (intake_scope unset / complex)
  → StrangeLoop … → GoalCompletionChunk (wire A)
Autopilot consensus
  → accept → complete_goal
  → thin / missing proof (evidence_follow_up) → queue_evidence_turn
        LoopRunRequest(
          same goal + workspace, prefer sticky slot,
          intake_scope="trivial",
          mission=collect_evidence,
          # max_iterations = agent.loop.max_iterations (shared)
        )
  → StrangeLoop trivial execute (tools) → GoalCompletionChunk (wire B)
  → consensus(goal, wire A + B) → accept | send_back(implement) | fail
```

Send_back for **rework** (wrong approach / missing impl) remains the
existing complex re-dispatch path. Trivial evidence turns are for **proof
gaps**, not product redesign.

---

## Wire / API

### Existing (reuse)

- `LoopRunRequest.intake_scope` — already on the runner protocol; client
  `loop_input.intake_scope` is the interactive analogue (RFC-450 / RFC-630).
- `GoalDispatchEnvelope` + `client_workspace` — already bind maker worktrees.
- `GoalCompletionChunk.evidence_summary` / contribution findings.

### Additive (this IG)

| Field | Where | Purpose |
|-------|--------|---------|
| `mission` | `GoalDispatchEnvelope` | `implement` \| `collect_evidence` |
| `mission_brief` | envelope | Consensus gaps / what to prove |
| `evidence_round` | envelope / CE | Distinguish implement vs evidence attempts |
| `evidence_follow_up` | `ConsensusVerdict` | Structured proof-gap vs rework |
| CE fields | `GoalNode` | `evidence_turn_count` (0\|1), `pending_mission`, `stashed_implement_response`, `evidence_prefer_loop_id` |

No AutopilotConfig knobs for evidence budgets — trivial intake +
`agent.loop.max_iterations` are the defaults.

Worker plumbs `request.intake_scope` into StrangeLoop for autopilot jobs.
For `collect_evidence`, `synthesize_sloop_response(..., prefer_full_output=True)`.

---

## Spec / doc updates

- [x] RFC-204 §1.3 implementation note — StrangeLoop evidence missions;
      ban host FS / marker hard-accept.
- [x] IG-710 — “Superseded in part by IG-724” pointer.
- [x] RFC-222 job contract — `mission` / evidence follow-up turn.
- [x] Debug wiki — “Thin consensus / evidence turn”.

---

## Work items

- [x] Extend dispatch envelope with `mission` + brief
- [x] Autopilot: plumb `intake_scope` on `LoopRunRequest` for evidence turns
- [x] Autopilot: consensus path → optional trivial evidence re-dispatch
      before implement send_back when proof-thin
- [x] Evidence turns use `intake_scope=trivial` + `agent.loop.max_iterations`
      (no AutopilotConfig evidence knobs)
- [x] Worker: autopilot path passes `intake_scope` into StrangeLoop
- [x] Packing: evidence missions prefer rich `full_output` on the wire
- [x] Unit tests: trivial evidence turn invoked; implement dispatch unchanged
- [x] `./scripts/verify_finally.sh` green

---

## Out of scope

- Host `bind_tools` consensus judge (explicitly rejected here).
- Replacing LoopRail / job scheduling with a job-level LangGraph.
- Forcing trivial scope on maker implement goals.
- Changing maturity / job-level acceptance (RFC-230 / IG-711).
- Architecture WavePlan host ingest gate (separate IGs).

---

## Success criteria

| Criterion | Target |
|-----------|--------|
| False send_back when commits + completion report exist | Drop via evidence turn + richer wire |
| Host FS reads in consensus | Zero |
| Agentic tools only in StrangeLoop | Always |
| Maker implement latency | Unchanged (trivial only on proof path) |
| Operator mental model | Engine requests; loop executes; host judges |
