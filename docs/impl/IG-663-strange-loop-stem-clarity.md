# IG-663: StrangeLoop Stem Clarity (Stations + Stages Layout)

**RFCs**: RFC-220 (Loop Graph), RFC-630 (intake routing), RFC-604 (assess/generate)
**Related**: RFC-201 (Plan-Execute conceptual), RFC-622 (clarification)
**Status**: Implemented

---

## Goal

Make the StrangeLoop LangGraph **readable like ReAct** without nested subgraphs:
a clear main stem (preprocess → plan → execute → complete), thematic station
names, and a `stages/` module layout that mirrors that stem.

## Non-goals

- LangGraph subgraph nesting
- Behavior changes to intake / assess / execute / clarification policies
- Changing soothe-sdk wire deliverable phases (`goal_completion`, `execute_step`)

## Design

### Stem stations (LangGraph node IDs)

| Legacy | New station | Stage |
|--------|-------------|-------|
| `intent_classify` | `intake` | preprocess |
| `init_or_resume` | `enter_loop` | preprocess |
| `bounded_evidence_gather` | `gather_evidence` | plan |
| `plan_gap_analysis` | `analyze_gaps` | plan |
| `plan_assess` | `assess` | plan |
| `plan_generate` | `generate_plan` | plan |
| `resolve_decision` | `commit_plan` | execute |
| `validate_evidence_bindings` | `validate_plan` | execute |
| `execute` | `execute` | execute |
| `record_iteration` | `record_progress` | execute |
| `iteration_gate` | `check_limits` | execute |
| `iteration_start` | `begin_iteration` | execute |
| `goal_completion` | `finalize` | complete |
| `await_clarification` | `await_user` | sidecar |
| `invoke_wired_subagent` | `delegate` | sidecar |

### Compatibility

- `sloop/orchestrator/stations.py` holds canonical IDs + legacy→canonical maps.
- Clarification origins and internal ledger `phase` filters accept **legacy or new**.
- Message deliverable phases `goal_completion` / `execute_step` remain wire-stable
  (finalize node still tags completion with `phase="goal_completion"`).

### Module layout

```text
sloop/stages/{preprocess,plan,execute,complete,sidecars}/
sloop/orchestrator/  # builder, routing, stations, state
```

### Docs

- Primary architecture diagram: `docs/diagrams/strange_loop_stem.mmd`
- Auto `draw_mermaid` dump remains an appendix for full edges

## Cleanse (IG-663 follow-up)

- Removed ``sloop/nodes/`` package and test ``orchestrator/nodes/`` directory
  (tests live under ``orchestrator/stages/``).
- Ledger writers keep **client-visible** phase strings (`intent_classify`,
  `plan_assess`, `plan_generate`, `plan_gap_analysis`, `goal_completion`,
  `execute_step`) so soothe-sdk / CLI checkpoint filters stay compatible.
- Host projection dual-reads legacy + station ids via ``stations.PLANNING_LEDGER_PHASES``.
- Langfuse run-name suffixes align with stem stations: ``intake``, ``evaluate``
  (children ``evaluate-gap`` / ``evaluate-gap-leg-*`` / ``evaluate-assess``;
  IG-672), ``generate-plan``, ``finalize``; root remains
  ``strange-loop-graph``; CoreAgent child remains ``execute-step``.

## Validation

- `./scripts/verify_finally.sh`
