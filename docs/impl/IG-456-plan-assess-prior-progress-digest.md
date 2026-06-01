# IG-456: Plan-Assess Prior-Progress Digest

> Implements RFC-227.

## Problem

`plan_assess` between iterations cannot see what the prior execute wave
actually produced. The RFC-214 ledger only stores one
`LoopHumanMessage`/`LoopAIMessage` pair per executed step (the final AI
text); raw tool messages — `run_command` stdout, file contents, search
results — stay out of `state.loop_messages`. The assess prompt fragment
(`prompts/fragments/instructions/plan_assess_instructions.xml`) also
never describes the `assessment_reasoning` field, so the LLM defaults to
restating the user's goal instead of summarizing prior progress.

Symptom in Langfuse trace `279a91c70f73f5b71fb31a5b61370f45`
("count all file types of the project", `kimi-k2.5`):

| Plan-assess | Iteration | Input tokens | Reasoning behavior |
|---|---|---|---|
| #1 | 0 | 469 | First call; no ledger yet. Baseline. |
| #2 | 1 | 1,154 | Restated the goal. Ignored 7 prior `run_command` results. |
| #3 | 2 | 1,643 | Restated the goal. Ignored 6 more `run_command` results. |
| #4 | 3 | 1,335 | Same pattern. Loop terminated only when final wave produced full answer. |

Execute calls saw 9k–15k input tokens of tool output; assess calls saw
1.1k–1.6k. The grounding gap propagates into `goal_progress` and
`status` decisions — extra iterations result.

## Root causes

1. **Prompt under-specifies the field.** `plan_assess_instructions.xml`
   documents `status`, `goal_progress`, and `require_goal_completion`,
   but never `assessment_reasoning`. The LLM freelances.
2. **No deterministic progress anchor.** The plan-context envelope has
   no `<PRIOR_PROGRESS>` block; nothing concrete tells assess "this is
   what just happened."
3. **Executor never produces a progress snapshot.**
   `_append_parallel_wave_ledger` writes the ledger pair and returns;
   nobody computes a per-wave digest.

## Fix scope

| Change | File |
|---|---|
| Add `ToolCallHead` + `PriorProgressDigest` schemas; add `LoopState.prior_progress: PriorProgressDigest \| None = None` | `packages/soothe/src/soothe/core/loop/state/schemas.py` |
| New `_update_prior_progress` helper; call from `_append_parallel_wave_ledger` after existing per-step appends | `packages/soothe/src/soothe/core/loop/engine/executor.py` |
| New `prior_progress` kwarg on `build_plan_context_envelope`; renders `<PRIOR_PROGRESS>` block when present and not stale; ≤600 char hard cap | `packages/soothe/src/soothe/core/prompts/user_envelope.py` |
| Thread `state.prior_progress` into the envelope for both `plan_phase="assess"` and `plan_phase="generate"` | `packages/soothe/src/soothe/core/prompts/builder.py` |
| Document `assessment_reasoning` contract; add "do not restate user request" guard | `packages/soothe/src/soothe/core/prompts/fragments/instructions/plan_assess_instructions.xml` |
| INFO log when digest `derived_progress_hint` and LLM `goal_progress` disagree by >1 bucket | `packages/soothe/src/soothe/core/loop/orchestrator/nodes/plan_assess.py` |

## Non-goals

- Projecting raw tool messages into `state.loop_messages` (inverts
  RFC-214/IG-380 separation between plan and CoreAgent ledger views).
- Replacing the LLM-emitted `assessment_reasoning` with a
  deterministically derived string.
- Touching the Loop Graph topology (no new nodes or edges; the
  `record_iteration → plan_assess` cycle is unchanged).
- Multi-wave history (`K > 1`). Digest is overwrite-only.
- Showing `<PRIOR_PROGRESS>` to `goal_completion` or
  `continuation_assess`.

## Design notes

- **One source of truth.** Executor produces; planner consumes; no
  third party recomputes.
- **Bounded by construction.** `tool_calls` ≤ 8, `evidence_excerpts` ≤ 3,
  each excerpt ≤ 200 chars, each tool head ≤ 120 chars, rendered block
  hard-capped at 600 chars.
- **Anchor, not override.** `derived_progress_hint` is shown verbatim
  to the LLM; never used as a code-side override of `StatusAssessment`.
- **Strictly additive.** `LoopState.prior_progress` defaults to `None`;
  envelope renders nothing when absent; older checkpoints deserialize
  unchanged.

### `derived_progress_hint` rule

1. `steps_failed > 0` → `"low"`.
2. Else if no tool calls AND no evidence excerpts → `"none"`
   (covers empty waves and successful-but-output-less steps; the LLM
   has nothing concrete to anchor on).
3. Else if ≥1 tool call AND ≥1 evidence excerpt contains a digit, `|`,
   or any of `done|completed|total|count|finished` (case-insensitive) →
   `"high"`.
4. Else → `"medium"`.

### Rendered block

```
<PRIOR_PROGRESS>
iter=<i> wave=<w> done=<sc> failed=<sf> hint=<hint>
tools:
- <name>: "<head>"
- ...
evidence:
- "<excerpt>"
- ...
</PRIOR_PROGRESS>
```

Trailing evidence lines drop first when the 600-char cap is hit; then
trailing tool lines.

### Disagreement log

Buckets `none < low < medium < high < complete`. When the LLM's
`goal_progress` is more than one bucket away from the digest's
`derived_progress_hint`, emit a single `INFO` line at the assess node:

```
[Plan] prior_progress hint=<hint> vs LLM goal_progress=<gp> (iter=<i>)
```

No code-side override of LLM output. Telemetry only.

## Tests

- `packages/soothe/tests/unit/core/loop/state/test_prior_progress_digest.py` —
  schema round-trip; field caps; `LoopState.prior_progress` defaults
  `None` and round-trips through `model_dump_json` /
  `model_validate_json`.
- `packages/soothe/tests/unit/core/loop/engine/test_update_prior_progress.py`
  - `test_all_success_with_evidence` → hint `"high"` when AI text has digits.
  - `test_all_success_no_signal` → hint `"medium"`.
  - `test_any_failure` → hint `"low"`.
  - `test_no_tools_no_text` → hint `"none"`.
  - `test_tool_heads_capped_at_8`.
  - `test_evidence_excerpts_capped_at_3_with_dedupe`.
  - `test_overwrites_each_wave` → second wave replaces first.
- `packages/soothe/tests/unit/core/prompts/test_envelope_prior_progress.py`
  - render with full payload, with empty heads, with stale digest
    (`prior_progress.iteration < current_iteration - 1`) → no block,
    and with 600-char cap forcing trailing-line drops.
- `packages/soothe/tests/unit/core/prompts/test_builder_prior_progress.py`
  - `plan_phase="assess"` and `plan_phase="generate"` both forward
    `state.prior_progress` to the envelope.
- `packages/soothe/tests/unit/core/prompts/test_plan_assess_fragment_contract.py`
  - fragment file contains an `assessment_reasoning` section AND a
    "do not restate" guard line.
- `packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_assess_disagreement_log.py`
  - hint `"low"` + LLM `goal_progress="high"` → INFO log line; aligned
    cases produce no log.
- `packages/soothe/tests/integration/core/test_loop_agent_prior_progress.py`
  - replay a "count file types" scenario with a stubbed planner; assert
    the assess #2 prompt contains `<PRIOR_PROGRESS>` with
    `steps_completed > 0`; assert the stub's recorded
    `assessment_reasoning` contains either a tool name or an evidence
    excerpt substring.

## Verification

`./scripts/verify_finally.sh` must pass (format + lint zero errors +
unit tests). Project rule per `CLAUDE.md`.
