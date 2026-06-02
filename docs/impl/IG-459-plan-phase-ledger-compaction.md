# IG-459: Plan-Phase Ledger Compaction (A2 + C1 + D1)

> Follow-up to RFC-214 / IG-456. Reduces three forms of interference in the
> plan-phase ledger that surfaced in Langfuse trace
> `19c3ed340552149f2aa95616cf375226` ("count only valid source code of
> @packages", `kimi-k2.5`).

## Problem

`LLMPlanner.assess_status` and `LLMPlanner.generate_from_assessment`
append (LoopHumanMessage, LoopAIMessage) pairs into `state.loop_messages`
so the next plan-phase call sees prior decisions. In the trace above,
plan-assess #2 received the iter=0 wave's evidence yet emitted
`assessment_reasoning` that echoed the iter=0 reasoning verbatim — and
its prompt-cache hit rate was 0 even though the system block was
identical.

Three concrete failure modes were identified from the trace metadata
and confirmed structurally in
`packages/soothe/tests/unit/core/prompts/test_plan_assess_anchoring_ablation.py`:

| Symptom | Trace evidence | Cause |
|---|---|---|
| 2nd plan-assess repeats the iter=0 reasoning | Same first sentence as #1 even after 17 `run_command` + 5 `ls` + 4 `read_file` results | The recorded plan-assess `LoopAIMessage` contains the full `StatusAssessment.model_dump()` — including `assessment_reasoning` — and the next assess anchors on it. |
| 2nd plan-assess `cache_read = 0` (#3 = 1,536) | System message sha256 identical across calls; only ledger differs | The recorded plan-assess / plan-generate humans carry `<CONTEXT_INFO>` (volatile `<timestamp>`), so the cache key changes every turn. |
| Goal appears in the prompt 3+ times | Iter=0 plan-assess human (`<USER_QUERY>`) + iter=0 plan-generate human (`<USER_QUERY>`) + current plan-context human (`<USER_QUERY>`) | The recorded `<USER_QUERY>` reads like a fresh directive on each turn, weakening recency for the latest evidence. |

The ablation harness measured deltas vs the production baseline before
this change:

```
condition                      msgs  chars  ~tok anchor <UQ>  Δchars
─────────────────────────────────────────────────────────────────────
baseline (pre-fix)               10   4914  1228   True    3       —
A2_compress_plan_assess_ai       10   4732  1183  False    3    -182
C1_strip_volatile_context        10   4716  1179   True    3    -198
D1_collapse_user_query           10   4914  1228   True    1      +0
```

A2 + C1 + D1 together: removes the anchor, restores cache-key stability,
and dedupes the goal — at −380 chars, zero messages dropped, planning
structure intact.

## Fix scope

| Change | File |
|---|---|
| New `compact_planning_human_content(content)` — strips `<CONTEXT_INFO>...</CONTEXT_INFO>` (C1) and rewrites `<USER_QUERY>...</USER_QUERY>` → `<GOAL_RECAP>...</GOAL_RECAP>` (D1). Idempotent; passthrough when markers absent. | `packages/soothe/src/soothe/core/loop/planning/ledger_compaction.py` (new) |
| New `compact_plan_assess_ai_dump(response)` — keeps `{status, goal_progress, require_goal_completion}`, drops `assessment_reasoning` (A2). Defensive fallback to `str(response)` on `model_dump()` failure or unrecognized schema. | same file |
| Apply compaction to the recorded human and AI in `assess_status` (uses both helpers). | `packages/soothe/src/soothe/core/loop/planning/planner.py` |
| Apply compaction to the recorded human in `generate_from_assessment` (C1 + D1 only; the AI dump stays verbatim because `steps` is the value of the recording). | same file |
| Re-export helpers from the planning package. | `packages/soothe/src/soothe/core/loop/planning/__init__.py` |

## Non-goals

- Dropping the planning ledger turns entirely (ablations A1/B1/B2). They
  are higher-impact but riskier — they remove the model's view of its
  prior decisions, which downstream auditing and `goal_completion` may
  depend on. Revisit only if A2 + C1 + D1 prove insufficient on a fresh
  trace.
- Compacting the plan-generate AI dump. `PlanGeneration.steps` IS the
  value of the recording; stripping anything from it loses the plan
  itself.
- Touching the rendered envelope sent to the *live* LLM call. Only the
  *stored* copy that re-enters the next prompt is compacted. The current
  turn's prompt is unchanged.
- Loop Graph topology. No new nodes, edges, or routing changes.

## Design notes

- **Single mutation point.** Both planner callsites copy the rendered
  human via `model_copy(update={"content": compacted})` before
  appending. Phase tags, `step_id`, `thread_id`, `iteration`, and other
  metadata fields stay intact so projection filters
  (`project_loop_messages_for_core_agent`, etc.) and serde round-trip
  unchanged.
- **A2 fallback chain.** `compact_plan_assess_ai_dump` is paranoid about
  schema drift: it preserves `str(raw)` when `model_dump` returns no
  recognized fields, and falls back to `str(response)` if `model_dump`
  raises. Recording loss would silently break audit trails, so prefer a
  verbose dump over an empty one when in doubt.
- **C1 regex stays narrow.** Only `<CONTEXT_INFO>...</CONTEXT_INFO>` is
  matched, with optional surrounding newlines, non-greedy and DOTALL.
  `<PRIOR_PROGRESS>` and `<SKILL_REFERENCE>` are preserved because they
  ground the next assess.
- **D1 is a string replace, not a regex.** `<USER_QUERY>` is a flat tag
  in every recorded envelope; replacement avoids ordering surprises if
  the envelope shape evolves.

## What the next assess sees, after this change

For the trace 19c3ed3 scenario, the iter=0 plan-assess + plan-generate
ledger pair now looks like:

```
LoopHumanMessage  phase=plan_assess   iter=0
   <GOAL_RECAP>count only valid source code …</GOAL_RECAP>
   <PRIOR_PROGRESS>…</PRIOR_PROGRESS>
   # <CONTEXT_INFO> stripped

LoopAIMessage     phase=plan_assess   iter=0
   {'status': 'replan', 'goal_progress': 'none', 'require_goal_completion': False}
   # assessment_reasoning dropped

LoopHumanMessage  phase=plan_generate iter=0
   <GOAL_RECAP>count only valid source code …</GOAL_RECAP>
   <PLAN_STEP_ID_HINT>…</PLAN_STEP_ID_HINT>
   # <CONTEXT_INFO> stripped

LoopAIMessage     phase=plan_generate iter=0
   {'plan_action': 'new', 'type': 'execute_steps', 'steps': [...], ...}
   # verbatim — plan IS the recording
```

Plus the current turn's plan-context human (with `<USER_QUERY>`,
`<PRIOR_PROGRESS>`, `<CONTEXT_INFO>`) unchanged.

## Tests

- `packages/soothe/tests/unit/core/loop/planning/test_ledger_compaction.py`
  - `test_compact_human_strips_context_info_block`
  - `test_compact_human_rewrites_user_query_to_goal_recap`
  - `test_compact_human_is_idempotent`
  - `test_compact_human_passthrough_when_no_markers`
  - `test_compact_plan_assess_drops_assessment_reasoning`
  - `test_compact_plan_assess_passthrough_for_none`
  - `test_compact_plan_assess_passthrough_for_non_pydantic`
  - `test_compact_plan_assess_falls_back_when_no_recognized_fields`
  - `test_compact_plan_assess_survives_model_dump_failure`
- `packages/soothe/tests/unit/core/loop/planning/test_planner_ledger_recording.py`
  - `test_assess_status_records_compacted_human_and_dropped_reasoning`
  - `test_generate_from_assessment_records_compacted_human_preserves_ai`
  - `test_recorded_humans_are_cache_stable_across_iterations`
  - `test_assess_status_does_not_record_when_llm_fallback_yields_no_response`
- `packages/soothe/tests/unit/core/prompts/test_plan_assess_anchoring_ablation.py`
  - Research harness — reproduces the pre-fix 8-turn ledger, applies
    each ablation (baseline, A1, A2, B1, B2, C1, D1) and asserts the
    structural deltas predicted in this document. Useful as a regression
    guard if the ledger format evolves.

## Verification

```bash
.venv/bin/pytest packages/soothe/tests/unit/core/loop/planning/ \
                 packages/soothe/tests/unit/core/prompts/ \
                 packages/soothe/tests/unit/middleware/test_system_prompt.py -q
# 603 passed
```

## Open questions

- **Live LLM ablation.** Structural deltas are confirmed; a live
  `StatusAssessment` call comparing the pre-fix and post-fix ledgers
  against the same goal would quantify the actual reasoning-quality
  delta. The ablation harness already exposes the rendered messages so
  this is a small follow-up.
- **Cache_read measurement.** The trace metric is the ground truth.
  Once a new trace lands post-deployment, compare plan-assess #2's
  `cache_read` against the pre-fix `cache_read=0`. Expected: substantial
  recovery from the now-stable recorded human prefix.
