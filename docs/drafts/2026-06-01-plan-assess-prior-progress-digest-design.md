# Plan-Assess Prior-Progress Digest Design

- **Status:** Draft (Platonic Brainstorming output)
- **Tracking:** IG-456 (to be filed when this draft becomes an RFC)
- **Date:** 2026-06-01
- **Owner area:** `soothe.core.loop` (executor, planning, prompt builder, schemas, prompt fragments)
- **Related specs:** RFC-214 (loop ledger), RFC-220 (loop graph), IG-264 (assess schema), IG-329 (plan instructions), IG-372 (assess-only fragment), IG-380 (plan ledger projection), IG-399 (descriptive progress).

---

## 1. Problem

Trace `279a91c70f73f5b71fb31a5b61370f45` (Langfuse, `kimi-k2.5`) shows the symptom clearly:

| Plan-assess call | Iteration | Input tokens | Observation |
|---|---|---|---|
| #1 | 0 | 469 | First call; no ledger yet. |
| #2 | 1 | 1,154 | Reasoning **restated the user's goal**, ignoring 7 prior `run_command` results. |
| #3 | 2 | 1,643 | Reasoning still re-stated the goal, ignoring an additional 6 `run_command` results. |
| #4 | 3 | 1,335 | Same pattern; loop only terminated because the final wave produced a complete answer. |

Concretely, assess #2 emitted:

> "The user wants to count all file types in the project. This requires scanning the project directory structure and categorizing files by their extensions. I need to execute shell commands to list files and count by extension, while excluding common directories like venv, .git, node_modules, etc."

This is plan-mode reasoning ("what I will do"), not assess-mode reasoning ("what the ledger now shows"). Two compounding causes:

1. **Prompt under-specifies the field.** `prompts/fragments/instructions/plan_assess_instructions.xml` documents `status`, `goal_progress`, and `require_goal_completion`, but never describes `assessment_reasoning`. The LLM freelances and defaults to goal restatement.
2. **The ledger the assess LLM sees is thin.** `engine/executor.py:_append_parallel_wave_ledger` records exactly one `LoopHumanMessage`/`LoopAIMessage` pair per executed step, with content sourced from the final AI text (and a `delegate_final` fallback). The raw tool messages (`run_command` stdout, file contents, search results) never enter `loop_messages`. So the assess prompt — which is built from `state.loop_messages` via `prompts/plan_ledger_projection.py` — sees a small, summary-only view of what actually happened.
3. **No progress anchor.** There is no `<PRIOR_PROGRESS>` or `<PREVIOUS_ASSESSMENT>` block in the assess prompt envelope. The model is asked to "judge progress" with nothing concrete to anchor on once the ledger is thin.

The downstream effect is not just cosmetic text: thin grounding also degrades the structured fields (`status`, `goal_progress`), which drive routing. The trace shows the loop ran four iterations for a task that finished as soon as it was given proper grounding.

## 2. Goal & non-goals

### Goals

- The LLM-emitted `assessment_reasoning` references actual evidence from the prior wave (tool names and/or output excerpts) instead of restating the goal.
- `status` and `goal_progress` reflect what executed: e.g., when the prior wave produced concrete results matching the request, `goal_progress` advances accordingly.
- Token cost of the assess prompt stays under ~2-3k input tokens (per the agreed budget).
- Single source of truth for "what just happened": one digest object produced once per wave, consumed by both assess and generate.

### Non-goals

- Restructuring the execute-step ledger or projecting tool messages into it.
- Removing the LLM-emitted `assessment_reasoning` field or deriving it deterministically.
- Changing the assess/generate split topology of the loop graph (RFC-220).
- Touching the CoreAgent ledger projection (`project_loop_messages_for_core_agent`).

## 3. Approach

A small, typed `PriorProgressDigest` is built by the executor at the end of every wave and stored on `LoopState.prior_progress`. The plan-context envelope renders it as a `<PRIOR_PROGRESS>` XML block, capped at ~600 chars. The assess instruction fragment is updated to (a) document `assessment_reasoning` semantics and (b) anchor it on `<PRIOR_PROGRESS>` while forbidding goal restatement. The same block is shown to plan-generate so replan decisions get the same grounding.

This is the minimum change that fixes both the surface bug (reasoning text) and the underlying grounding gap (decision quality), inside the agreed token envelope.

## 4. Design

### 4.1 New schema types — `state/schemas.py`

```python
class ToolCallHead(BaseModel):
    """One tool invocation from the most recent wave."""
    name: str = Field(max_length=64)        # e.g. "run_command", "read_file"
    head: str = Field(default="", max_length=120)  # first non-empty line of output

class PriorProgressDigest(BaseModel):
    """Compact, truthful snapshot of the most recent execute wave.

    Refreshed by the executor after every wave (parallel or sequential).
    Consumed by plan-assess and plan-generate as the `<PRIOR_PROGRESS>` anchor.
    Never used as a code-side override for the LLM's structured output.
    """
    iteration: int
    wave_index: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    tool_calls: list[ToolCallHead] = Field(default_factory=list, max_length=8)
    evidence_excerpts: list[str] = Field(default_factory=list, max_length=3)  # each ≤200 chars
    derived_progress_hint: Literal["none","low","medium","high"] = "low"
```

`LoopState` gains `prior_progress: PriorProgressDigest | None = None` (defaults preserve checkpoint backward compatibility — older checkpoints simply load with `None`).

### 4.2 Executor — `engine/executor.py`

Inside `_append_parallel_wave_ledger`, after the existing per-step ledger append loop, call:

```python
self._update_prior_progress(state, steps, gather_results, wave_index=...)
```

`_update_prior_progress` is new and does only:

1. Count successes / failures from `gather_results`.
2. Extract up to 8 `ToolCallHead`s from `step_messages` of the wave: walk messages looking for `AIMessage` tool calls and the matching `ToolMessage` results, take the tool name and the first non-empty line of the output (≤120 chars). Cap total at 8 oldest-first.
3. Take up to 3 `evidence_excerpts`: per successful step, take the first 200 chars of the final AI text (the same text written to the ledger), dedupe by prefix, keep last 3.
4. Compute `derived_progress_hint` with a small rule:
   - any failures → `low`
   - zero tool calls and empty AI text → `none`
   - tool calls present + non-empty AI text containing digits, table glyphs (`|`), or words like `done`, `completed`, `total`, `count` → `high`
   - otherwise → `medium`
5. Replace `state.prior_progress` with the new digest (it always reflects the *most recent* wave; we do not accumulate).

The executor change is local and additive. No other ledger behavior moves.

### 4.3 Envelope — `prompts/user_envelope.py`

`build_plan_context_envelope` gains a new optional kwarg `prior_progress: PriorProgressDigest | None = None`. When set, it appends a `<PRIOR_PROGRESS>` block before `<CONTEXT_INFO>`:

```
<PRIOR_PROGRESS>
iter=2 wave=0 done=6 failed=0 hint=medium
tools:
- run_command: "find . -type f -name '*.py' | wc -l"
- run_command: "1139"
- run_command: "find . -type f -name '*.json' | wc -l"
evidence:
- "Counted .py: 1139, .json: 665, .md: 217"
- "Excluded venv, .git, node_modules"
</PRIOR_PROGRESS>
```

Rendering rules:

- Whole block hard-capped at 600 chars; trailing items dropped before truncation.
- Each `tool_calls` line: `name: "head"`; empty `head` is dropped.
- `evidence` items rendered as JSON-escaped quoted strings.
- When `prior_progress` is `None` or its iteration < current `state.iteration - 1`, the block is omitted (avoid showing stale data).

### 4.4 Prompt builder — `prompts/builder.py`

`_build_plan_context_human_text` reads `state.prior_progress` and passes it to `build_plan_context_envelope` for **both** `plan_phase == "assess"` and `plan_phase == "generate"`. No other phase consumes it.

### 4.5 Assess prompt fragment — `prompts/fragments/instructions/plan_assess_instructions.xml`

Add a new section after the existing `require_goal_completion` block:

```
**assessment_reasoning** (≤2 sentences, ≤500 chars)
- Sentence 1: summarize what `<PRIOR_PROGRESS>` (when present) shows about progress
  toward the goal — name a tool that ran, an evidence excerpt, or both. Do NOT
  restate the user's request; that is what `<USER_QUERY>` is for.
- Sentence 2: justify your `status` choice given that evidence.
- If `<PRIOR_PROGRESS>` is absent (first assess of the goal), say so plainly and
  base reasoning on `<USER_QUERY>` only.
```

Tighten the existing `**Guards**` list with:

```
- Do NOT restate the user's request in `assessment_reasoning`. Cite ledger or
  `<PRIOR_PROGRESS>` evidence instead.
```

The generate fragment is **not** changed in this design — `<PRIOR_PROGRESS>` is purely additive context to generate; the existing `<PLAN_DAG_CONTEXT>` continues to drive step authoring.

### 4.6 Logging & telemetry

When the digest carries `derived_progress_hint` and the LLM returns a `goal_progress` that disagrees by more than one bucket (`none↔medium`, `low↔high`, anything→`complete`), log a single `INFO` line at the assess node:

```
[Plan] prior_progress hint=%s vs LLM goal_progress=%s (iter=%d)
```

No code-side override. The log is for offline tuning.

## 5. Data flow

```
execute wave finishes (executor._execute_wave)
  └── _append_parallel_wave_ledger (existing)
       ├── append Human/AI per step                # unchanged
       └── _update_prior_progress(state, ...)      # NEW: writes state.prior_progress

plan_assess node (next iteration)
  └── plan_phase.assess_status(...)
       └── prompt_builder.build_plan_messages(plan_phase="assess")
            └── _build_plan_context_human_text(...)
                 └── build_plan_context_envelope(..., prior_progress=state.prior_progress)
                      └── renders <PRIOR_PROGRESS> block

plan_generate node (same iteration, after assess)
  └── prompt_builder.build_plan_messages(plan_phase="generate")
       └── _build_plan_context_human_text(...)
            └── build_plan_context_envelope(..., prior_progress=state.prior_progress)
                 └── renders <PRIOR_PROGRESS> block
```

The digest is overwritten each wave; assess and generate within a single iteration see the same snapshot.

## 6. Backwards compatibility

- `LoopState.prior_progress` defaults to `None`. Older checkpoints deserialize unchanged; new field is set on the next wave they execute.
- Envelope and builder changes are no-ops when `prior_progress is None`.
- Prompt fragment edits are additive; no removed instructions. Existing tests that snapshot fragment shape will need an updated fixture.

## 7. Testing

All test files live under `packages/soothe/tests/...` per CRITICAL RULE 4 (tests beside the code they cover).

### Unit (`packages/soothe/tests/unit/`)

- `core/loop/state/test_prior_progress_digest.py`: `PriorProgressDigest` round-trip + field caps.
- `core/loop/engine/test_update_prior_progress.py`:
  - `test_update_prior_progress_all_success` — N steps, all success, hint = `high` or `medium` depending on content.
  - `test_update_prior_progress_with_failures` — at least one failure → hint = `low`.
  - `test_update_prior_progress_extracts_tool_heads` — multi-tool wave, head capped at 120 chars, list capped at 8.
  - `test_update_prior_progress_overwrites_each_wave` — second wave replaces first.
- `core/prompts/test_envelope_prior_progress.py`: `test_envelope_prior_progress_render` + `test_envelope_omits_stale_prior_progress`.
- `core/prompts/test_builder_prior_progress.py`: `test_build_plan_messages_passes_prior_progress` for both `plan_phase` values.
- `core/prompts/test_plan_assess_fragment_contract.py`: assert the new `assessment_reasoning` section is present in `plan_assess_instructions.xml`.

### Integration (`packages/soothe/tests/integration/`)

- `core/test_loop_agent_prior_progress.py`: replay the "count file types" scenario with a stub planner that asserts:
  - Plan-assess #2's prompt contains `<PRIOR_PROGRESS>` with `steps_completed > 0`.
  - The synthetic LLM stub's recorded `assessment_reasoning` contains at least one of the tool names or an evidence excerpt substring.
  - `goal_progress` advances past `none` by assess #2.

### Replay regression

- Re-run a checked-in trace fixture (or add one) and snapshot the new assess prompt text to lock in the format.

## 8. Migration & rollout

- Single PR, single IG (**IG-456**).
- No config flag required; the new behavior is strictly additive when the digest is present and a no-op when it isn't.
- Update `config/config.template.yml` only if a knob emerges during review (none planned today).
- Run `./scripts/verify_finally.sh` before commit per project rules.

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Digest extraction is wrong for delegate/subagent waves and shows noisy tool names. | `_update_prior_progress` filters to known tool message types; subagent results contribute via `delegate_final` text as an `evidence_excerpts` entry, not a `ToolCallHead`. |
| LLM clings to `derived_progress_hint` and stops grading independently. | Hint is one short word in a 600-char block; the prompt does NOT instruct the model to defer to it. Disagreement logging gives signal without code-level override. |
| Cache key churn from per-wave digest changes invalidates the prompt prefix cache. | The digest sits in the dynamic user-context message at the end of the prompt, AFTER the cached system + ledger. The cache prefix remains stable; only the trailing user message changes — same shape as today. |
| Ledger text and digest can disagree (digest says `hint=high`, ledger AI text says "I will…"). | Acceptable. The digest is sourced from the same AI text and tool calls, so disagreement implies a parser bug that tests will catch. |
| Prompt fragment edit invalidates existing prompt snapshot tests. | Update the snapshots in the same PR; fragment-shape tests are explicit about additive sections. |

## 10. Out of scope / future work

- Projecting raw tool messages into the execute-step ledger (a larger ledger redesign).
- Replacing the LLM-emitted `assessment_reasoning` with a deterministically derived string.
- Showing `<PRIOR_PROGRESS>` to `goal_completion` or `continuation_assess`.
- Persisting per-wave digests as a history list (today we keep only the latest).

## 11. Open questions for RFC stage

1. Should `evidence_excerpts` prefer the *last* AI text per step, or the longest one? (Current design: last.)
2. Should subagent results contribute a synthetic `ToolCallHead` entry with name `"subagent:<role>"`? (Current design: no; they appear in `evidence_excerpts` only.)
3. Do we want a `prior_progress_window` of the last K waves (not just last) once we have telemetry on disagreement frequency? (Current design: K=1.)

---

## Next step

Hand off to Platonic Coding Phase 1: generate the RFC for this design and then run `specs-refine`.
