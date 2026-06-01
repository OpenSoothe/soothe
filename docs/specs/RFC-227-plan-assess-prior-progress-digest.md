# RFC-227: Plan-Assess Prior-Progress Digest

**RFC**: 227
**Title**: Plan-Assess Prior-Progress Digest
**Status**: Draft
**Kind**: Architecture Design
**Authors**: xiaming
**Created**: 2026-06-01
**Last Updated**: 2026-06-01
**Depends on**: RFC-214, RFC-220
**Related**: RFC-201 (plan-execute loop), RFC-206 (prompt architecture), RFC-219 (goal completion), RFC-604 (reason-phase split), IG-264 (StatusAssessment schema), IG-329 (plan instructions), IG-372 (assess-only fragment), IG-380 (plan ledger projection), IG-399 (descriptive progress)
**Supersedes**: ---

---

## 1. Abstract

`plan_assess` is structurally starved of evidence between iterations. The RFC-214 unified message ledger captures only one `LoopHumanMessage`/`LoopAIMessage` pair per executed step (the final AI text), not the underlying tool messages. The assess prompt fragment (IG-329, IG-372) documents `status`, `goal_progress`, and `require_goal_completion`, but never describes the `assessment_reasoning` field — so the assess LLM defaults to restating the user's goal instead of summarizing prior progress. The compounding effect is wrong `goal_progress` and unnecessary extra iterations.

This RFC introduces a typed `PriorProgressDigest` value, produced by the executor at the end of every wave and stashed on `LoopState.prior_progress`. The plan-context envelope renders the digest as a `<PRIOR_PROGRESS>` XML block (≤600 chars) for both the `plan_assess` and `plan_generate` phases. The assess instruction fragment is updated to specify the `assessment_reasoning` contract: anchor on `<PRIOR_PROGRESS>` evidence, do not restate the user query. The change is additive, requires no graph topology change, and stays inside the existing assess token envelope.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

- A new typed value `PriorProgressDigest` (and sub-type `ToolCallHead`) on `soothe.core.loop.state.schemas`.
- A new field `LoopState.prior_progress: PriorProgressDigest | None = None`.
- A new executor helper `_update_prior_progress` invoked from `_append_parallel_wave_ledger`.
- A new `<PRIOR_PROGRESS>` block rendered by `build_plan_context_envelope` when the digest is present.
- A documented contract for `StatusAssessment.assessment_reasoning` in `prompts/fragments/instructions/plan_assess_instructions.xml`.
- Telemetry behavior for digest/LLM disagreement on `goal_progress`.

### 2.2 Non-Goals

This RFC does **not** change:

- The Loop Graph topology (no new nodes or edges; the `record_iteration → plan_assess` cycle is unchanged).
- The execute-step ledger contents in `LoopState.loop_messages` (tool messages are NOT projected into the ledger).
- `StatusAssessment` schema fields (the field already exists; only the prompt contract changes).
- The CoreAgent ledger projection (`project_loop_messages_for_core_agent` is untouched).
- The continuation-assess discriminator (RFC-226) on iter=0; that path does not consume the digest.
- The `goal_completion` node prompt or schema.

---

## 3. Background and Motivation

### 3.1 Observed defect

Trace `279a91c70f73f5b71fb31a5b61370f45` (Langfuse, `kimi-k2.5`, user request "count all file types of the project") exhibits the symptom across four plan-assess iterations:

| Plan-assess call | Iteration | Input tokens | Observation |
|---|---|---|---|
| #1 | 0 | 469 | First call; no ledger yet — reasoning baseline. |
| #2 | 1 | 1 154 | Reasoning restated the user's goal, ignoring 7 prior `run_command` results. |
| #3 | 2 | 1 643 | Reasoning still restated the goal, ignoring 6 more `run_command` results. |
| #4 | 3 | 1 335 | Same pattern. Loop terminated only because the final wave produced a complete answer. |

The literal text emitted at assess #2:

> *"The user wants to count all file types in the project. This requires scanning the project directory structure and categorizing files by their extensions. I need to execute shell commands to list files and count by extension, while excluding common directories like venv, .git, node_modules, etc."*

This is plan-mode reasoning ("what I will do"), not assess-mode reasoning ("what the ledger now shows").

### 3.2 Root causes

1. **Prompt under-specifies `assessment_reasoning`.** The assess instruction fragment (IG-329, IG-372) documents `status`, `goal_progress`, and `require_goal_completion`. The `assessment_reasoning` field exists on `StatusAssessment` (IG-264) but is never described in the prompt. The LLM defaults to a generic goal restatement.
2. **The assess LLM sees a thin ledger.** `_append_parallel_wave_ledger` records one `LoopHumanMessage`/`LoopAIMessage` pair per executed step (RFC-214). Content is sourced from the final AI text (`extract_text_from_message_content` over the last `AIMessage`) or `delegate_final` for subagent waves. The raw tool messages (`run_command` stdout, file contents, search results) are intentionally not in `loop_messages` because the CoreAgent thread should not be polluted by plan-phase noise (IG-380 splits the projection per consumer). Net effect: assess gets ~1–2 K tokens, while execute saw ~9–15 K of tool output.
3. **No deterministic progress anchor.** The plan-context envelope has no `<PRIOR_PROGRESS>` block. The model is asked to "judge progress" with no concrete handle once the ledger is sparse.

### 3.3 Why a minimal digest, not a ledger expansion

A larger fix — projecting tool messages into the ledger — would invert the RFC-214/IG-380 separation of concerns (plan vs CoreAgent ledger views) and could expand the prompt by 5–15× per assess call. A small, typed, deterministic snapshot keeps the assess prompt bounded (~600 chars added), produces a single source of truth for "what the last wave did," and lets plan-generate reuse the same anchor.

---

## 4. Design Principles

1. **One digest per wave, overwrite-only.** The digest reflects the *most recent* wave. No history list; older waves are durably visible via the ledger as before.
2. **Executor owns production; planner owns consumption.** The same module that knows what just ran writes the digest. The prompt builder only reads it. No third party computes it lazily.
3. **Bounded by construction.** Field caps (`max_length`, `max_items`) ensure the digest cannot grow with workload. The rendered block is hard-capped at 600 chars.
4. **Anchor, do not override.** `derived_progress_hint` is shown to the LLM verbatim. The LLM is free to disagree. No code-side rewrite of `StatusAssessment` values.
5. **Strictly additive.** Default `None` preserves existing checkpoint deserialization. When `prior_progress is None`, the envelope renders no `<PRIOR_PROGRESS>` block and the assess prompt behaves as today.
6. **Same anchor for assess and generate.** Both phases benefit from the same grounding signal; the envelope passes it to either when present.

---

## 5. Architecture

### 5.1 Data flow

```
execute wave finishes
   (engine/executor._execute_wave → _append_parallel_wave_ledger)
        │
        ├── append Human/AI per step  (unchanged, RFC-214)
        │
        └── _update_prior_progress(state, steps, gather_results, wave_index)
                writes state.prior_progress  (NEW)

record_iteration → iteration_gate → iteration_start → bounded_evidence_gather
        │
        ▼
plan_assess
   (orchestrator/nodes/plan_assess.node_plan_assess)
        │
        └── plan_phase.assess_status(...)
              └── prompt_builder.build_plan_messages(plan_phase="assess")
                    └── _build_plan_context_human_text(...)
                          └── build_plan_context_envelope(
                                  ..., prior_progress=state.prior_progress
                              )
                                └── renders <PRIOR_PROGRESS> when present

(if assess routes to generate)
plan_generate
   (orchestrator/nodes/plan_generate.node_plan_generate)
        │
        └── prompt_builder.build_plan_messages(plan_phase="generate")
              └── _build_plan_context_human_text(...)
                    └── build_plan_context_envelope(
                            ..., prior_progress=state.prior_progress
                        )
                          └── renders <PRIOR_PROGRESS> when present
```

The graph topology, node identities, and edges are unchanged.

### 5.2 PriorProgressDigest schema

```python
class ToolCallHead(BaseModel):
    """One tool invocation captured from the most recent execute wave."""
    name: str = Field(max_length=64)         # e.g. "run_command", "read_file"
    head: str = Field(default="", max_length=120)
    # first non-empty line of the tool message content,
    # whitespace-stripped, truncated at 120 chars

class PriorProgressDigest(BaseModel):
    """Compact, truthful snapshot of the most recent execute wave (RFC-227).

    Refreshed by the executor at the end of every wave (parallel or sequential).
    Consumed by plan-assess and plan-generate as the <PRIOR_PROGRESS> anchor.
    Never used as a code-side override for the LLM's structured output.
    """
    iteration: int                                      # iteration that produced the wave
    wave_index: int = 0                                 # 0-based wave within the iteration
    steps_completed: int = 0
    steps_failed: int = 0
    tool_calls: list[ToolCallHead] = Field(default_factory=list, max_length=8)
    evidence_excerpts: list[str] = Field(default_factory=list, max_length=3)
    # each excerpt ≤ 200 chars, deduped by 64-char prefix
    derived_progress_hint: Literal["none","low","medium","high"] = "low"
```

`LoopState` gains one optional field:

```python
class LoopState(...):
    # ... existing fields ...
    prior_progress: PriorProgressDigest | None = None
```

Default `None` is required for backward checkpoint deserialization.

### 5.3 Executor responsibilities

`engine/executor.py:_append_parallel_wave_ledger` is extended to call a new helper after its existing ledger-append loop:

```python
def _append_parallel_wave_ledger(self, state, steps, gather_results, *, wave_index=0) -> None:
    # ... existing per-step ledger appends ...
    self._update_prior_progress(state, steps, gather_results, wave_index=wave_index)
```

`_update_prior_progress` is purely deterministic and does only the following:

1. **Counts.** `steps_completed` = number of `gather_results[i]` whose `step_result.success` is True. `steps_failed` = complement.
2. **Tool heads.** For each step's `step_messages`, walk forward over `AIMessage` instances and collect at most 8 `(name, head)` pairs in arrival order from `AIMessage.tool_calls`. The head is `_first_arg_head_for_tool_call(call)` — the first non-empty argument value, single-line, stripped, capped at 120 chars. Empty heads are kept (`head=""`) to preserve the tool-name signal. Tool **names** come from `AIMessage.tool_calls` (not from `ToolMessage` walks) because `Executor._stream_and_collect` does not append `ToolMessage` to its returned `messages` list — they are routed into outcome/budget accounting and excluded from the list on purpose. A `ToolMessage` walk would miss every call.
3. **Evidence excerpts.** For each step, use `Executor._ledger_execute_ai_content(messages=step_messages, final_ai_msg=last_AIMessage, total_steps=1)` — the same helper that builds the ledger AI body. It returns the final-AIMessage content when non-empty, otherwise the assembled text across `AIMessageChunk` entries, and appends the `<LAST_TOOL_RESULT>` block when a `ToolMessage` happens to be present. Fall back to `delegate_final` text for `task`-tool waves. Keep `text.strip()[:200]`, dedupe by 64-char prefix, cap the list at 3 most-recent entries.
4. **Derived progress hint.** Pure-Python rule:
   - `steps_failed > 0` → `"low"`.
   - No tool calls AND no evidence excerpts → `"none"` (covers empty waves and successful-but-output-less steps; the LLM has nothing concrete to anchor on).
   - At least one tool call AND at least one evidence excerpt containing either digit characters, the pipe character `|`, or any of `done|completed|total|count|finished` (case-insensitive) → `"high"`.
   - Otherwise → `"medium"`.
5. **Assignment.** `state.prior_progress = PriorProgressDigest(iteration=state.iteration, wave_index=wave_index, ...)`.

The digest is overwritten, never appended. Sequential waves within the same iteration produce one digest per wave, and the latest wins.

### 5.4 Envelope rendering

`prompts/user_envelope.build_plan_context_envelope` gains an optional kwarg:

```python
def build_plan_context_envelope(
    *,
    goal: str,
    dag_context: str | None = None,
    step_id_hint: str | None = None,
    goal_user_submission: str | None = None,
    skill_context: SkillContext | None = None,
    prior_progress: PriorProgressDigest | None = None,   # NEW
) -> str: ...
```

When `prior_progress` is set AND `prior_progress.iteration >= state.iteration - 1` (i.e. not stale), the envelope appends:

```
<PRIOR_PROGRESS>
iter=<iteration> wave=<wave_index> done=<steps_completed> failed=<steps_failed> hint=<derived_progress_hint>
tools:
- <name>: "<head>"
- ...
evidence:
- "<excerpt>"
- ...
</PRIOR_PROGRESS>
```

Rendering rules:

- The whole block is hard-capped at 600 chars; trailing items (evidence first, then tools) are dropped before any single-line truncation.
- `tools` line items with empty `head` render as `- <name>: ""`.
- `evidence` strings are JSON-escaped before being placed inside double quotes.
- When `prior_progress is None` or stale, no block is emitted (no marker, no comment).

### 5.5 Prompt builder integration

`prompts/builder.PromptBuilder._build_plan_context_human_text` reads `state.prior_progress` and forwards it for both phases:

```python
return build_plan_context_envelope(
    goal=goal,
    dag_context=dag_context,
    step_id_hint=step_id_hint,
    goal_user_submission=state.goal_user_submission,
    skill_context=state.skill_context,
    prior_progress=state.prior_progress,   # NEW; both assess and generate
)
```

No `plan_phase` branching is needed — the envelope simply omits the block when the field is absent.

### 5.6 Assess prompt fragment

`prompts/fragments/instructions/plan_assess_instructions.xml` gains a new `assessment_reasoning` section after the existing `require_goal_completion` paragraph, and tightens the existing `Guards` list:

```
**assessment_reasoning** (≤2 sentences, ≤500 chars)
- Sentence 1: summarize what `<PRIOR_PROGRESS>` (when present) shows about progress
  toward the goal — cite a tool that ran, an evidence excerpt, or both. Do NOT
  restate the user's request; that is what `<USER_QUERY>` is for.
- Sentence 2: justify your `status` choice given that evidence.
- If `<PRIOR_PROGRESS>` is absent (first assess of the goal), say so plainly and
  base reasoning on `<USER_QUERY>` only.

**Guards**
- ... existing guards ...
- Do NOT restate the user's request in `assessment_reasoning`. Cite ledger or
  `<PRIOR_PROGRESS>` evidence instead.
```

The generate fragment is not changed — `<PRIOR_PROGRESS>` is additive context, and `<PLAN_DAG_CONTEXT>` continues to drive step authoring.

### 5.7 Telemetry

`orchestrator/nodes/plan_assess.node_plan_assess` emits a single `INFO` log when the digest hint and the LLM's `goal_progress` disagree by more than one bucket on the ordered scale (`none < low < medium < high < complete`):

```
[Plan] prior_progress hint=%s vs LLM goal_progress=%s (iter=%d)
```

The log is for offline tuning. There is no code-side override of `StatusAssessment` values.

### 5.8 Cache behavior

Plan prompts are cached by prefix (system + projected ledger + native prior-conversation turns). The new `<PRIOR_PROGRESS>` block sits inside the trailing plan-context user message, AFTER the cached prefix — the same shape as today's envelope additions (`<PLAN_DAG_CONTEXT>`, `<PLAN_STEP_ID_HINT>`). Cache hit rate on the prefix is preserved; only the trailing user message changes per wave, as it already does today.

---

## 6. Backwards compatibility

- `LoopState.prior_progress` defaults to `None`. Older checkpoints deserialize unchanged; the next executed wave populates the field.
- `PriorProgressDigest` and `ToolCallHead` are new types; no existing schema changes.
- Envelope and prompt-builder changes are no-ops when `prior_progress is None`.
- Prompt fragment edits are additive. Fragment-shape tests are updated in the same change.
- No config flag is required; no new `agent.loop.*` knob is introduced.

---

## 7. Relationship to other RFCs

- **RFC-214 (Volatility-Tiered Prompt Architecture & Unified Message Ledger):** `prior_progress` is a sibling to `loop_messages`, not a replacement. The ledger continues to be the durable, replayable record; the digest is a per-wave projection for plan prompts only.
- **RFC-220 (LangGraph Agent Loop Orchestrator):** No graph nodes or edges are added. The new field rides on the same `LoopState` already routed through the graph.
- **RFC-206 (Hierarchical Prompt Architecture):** `<PRIOR_PROGRESS>` is an additional dynamic user-context block; it does not alter the layered ordering (SYSTEM_CONTEXT → INSTRUCTIONS → USER_TASK).
- **RFC-219 (Goal Completion Module):** Goal completion does not consume the digest. It continues to source its evidence from the ledger and final AI text.
- **RFC-226 (Continuation-Aware plan_assess):** The iter=0 continuation discriminator path is unchanged. On iter=0 with no executed waves, `prior_progress` is `None`, so the bootstrap and `plan_generate` branches behave exactly as today.
- **RFC-604 (Plan Phase Robustness):** The `assessment_reasoning` contract reinforces the three-layer defense: the LLM is steered toward truthful summarization, the deterministic hint provides a sanity comparator, and existing guards (stuck detection, `done`-at-iter-0 rejection in `assess_status`) remain in place.

---

## 8. Open questions

1. **Excerpt selection.** When a step's `step_messages` contain multiple AI texts, do we keep the *last* (current proposal) or the *longest*? Last matches what is already written to the ledger; longest may carry more evidence but can deviate from what the LLM downstream sees.
2. **Subagent contribution.** Should subagent results contribute a synthetic `ToolCallHead` entry with name `"subagent:<role>"`, or stay confined to `evidence_excerpts` (current proposal)?
3. **History window.** Today we keep K=1 (overwrite). Once telemetry shows disagreement frequency, do we promote to K-last waves (e.g. K=2 or K=3) — and if so, where do we cap the total rendered chars?
4. **Hint visibility.** The hint is shown verbatim. If telemetry shows the LLM defers excessively, an alternative is hint-omitted-from-prompt (telemetry-only). This RFC keeps the in-prompt variant; the question is whether the toggle is worth a config flag.
5. **Generate-phase impact.** Does `<PRIOR_PROGRESS>` on the generate path interact with `<PLAN_DAG_CONTEXT>` in ways that need spec-level coordination (e.g. when DAG says "ready_step_ids" but the digest says all steps succeeded)?

---

## 9. Conclusion

`plan_assess` does not currently see enough of what just happened, and does not know that its `assessment_reasoning` should summarize that evidence. Both halves of the gap are addressed by one small, typed, executor-owned snapshot rendered as a single XML block, plus one paragraph of prompt contract. The change preserves the RFC-214 ledger split, the RFC-220 graph topology, and the RFC-226 continuation path; it is strictly additive when the digest is absent and bounded by construction when present. The downstream effect — truthful reasoning text plus better-grounded `status`/`goal_progress` decisions — directly attacks the wasted-iteration pattern visible in the motivating trace.
