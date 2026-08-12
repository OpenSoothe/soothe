# Prompt Assembly Analysis Findings

**Created**: 2026-08-12
**Kind**: Analysis (findings record)
**Scope**: `soothe.autopilot.prompts` + `soothe.sloop.prompts` prompt assembly
**Related**: [RFC-206](../specs/RFC-206-prompt-architecture.md),
[IG-736](IG-736-autopilot-prompts-module.md), [IG-705](IG-705-autopilot-one-level-layout.md)

---

## 1. Purpose

This document records the analysis of the prompt-assembly code paths traced in
PGC-01 (component discovery) and PGC-02 (flow tracing). It is a reference for
future changes to prompt assembly and validates conformance to RFC-206's
hierarchical system/user separation.

## 2. Two-Tier Assembly Summary

Prompt assembly in `soothe` is split across two independently-structured layers
that share the same `[SystemMessage, HumanMessage]` composition shape but differ
in richness:

| Layer | Package | Composer | Consumers |
|-------|---------|----------|-----------|
| Autopilot DAG-level | `soothe.autopilot.prompts` | `render_*` builders (thin `.format`) | `verifier_reasoner.py`, `backoff_reasoner.py`, consensus/maturity/rail guards |
| StrangeLoop execution-level | `soothe.sloop.prompts` | `PromptBuilder.build_plan_messages` (hierarchical) | `planner.py` (assess / generate / gap / continuation call sites) |

Both tiers conform to RFC-206's **Layer 1 (SYSTEM_CONTEXT) + Layer 2 (USER_TASK)**
separation: static policy/role text lives in prefetched fragments
(`fragments/__init__.py`); per-call dynamic facts are bound via builders.

## 3. Autopilot Assembly (DAG-level)

### 3.1 Entry & composition
- **Entry**: `DagVerificationReasoner.analyze_placement(context)` →
  `verifier_reasoner.py:354`.
- **System prompt**: `SYSTEM_GOAL_PLACEMENT` (from `roles.py`).
- **User prompt**: `render_goal_placement_prompt(...)` in `verify.py:96`,
  which `.format()`-binds `GOAL_PLACEMENT_PROMPT` (loaded once at import from
  `fragments/verify/goal_placement.xml`).
- **Compose**: `messages = [SystemMessage(role), HumanMessage(rendered)]`.
- **Invoke**: `_invoke_llm(prompt, system_prompt, operation="placement")` with
  structured parse into `GoalPlacementResponse`.

### 3.2 Parallel render functions (same flow)
`render_backoff_prompt`, `render_dag_health_prompt`,
`render_post_completion_prompt` — each binds its own `fragments/` template and
is consumed by the matching `analyze_*` method in `verifier_reasoner.py` /
`backoff_reasoner.py` via the identical compose → `_invoke_llm` path.

### 3.3 Conformance notes (IG-736)
- One-level package (`soothe.autopilot.prompts.*` only) — verified.
- No inline `"You are an expert…"` in reasoners — roles centralized in
  `roles.py`.
- Guard injection boundary respected: SECURITY RULES live in system fragment;
  operator/agent summaries wrapped via `wrap_untrusted()` (`envelopes.py`) with
  `<untrusted_data>` markers.
- Behavior freeze holds: consensus vocab (`accept`/`send_back`/`fail`),
  maturity signals, verifier JSON keys unchanged.

## 4. StrangeLoop Assembly (execution-level)

### 4.1 Entry & composition
- **Entry**: `Planner._plan_assess` / `_plan_generate` / `_plan_gap` /
  `_continuation_assess` → `planner.py` (lines ~644, ~1102, ~1190, ~1425).
- **Composer**: `PromptBuilder.build_plan_messages(goal, state, context,
  call_kind=kind, ...)` in `builder.py:107`.

### 4.2 Pipeline stages
1. **Projection mode resolution** — `resolve_planner_projection_mode(state)`
   → `"new_goal" | "mid_goal"`.
2. **Ledger projection** (kind-dependent, `plan_ledger_projection.py`):
   - `continuation` → `project_continuation_assess_ledger`
   - `assess` / `gap` → `project_planner_ledger_for_assess`
   - `generate` → `project_planner_ledger`
   - Cross-goal boundaries via `projected_ledger_has_goal_completion`.
3. **System message assembly** — `_build_system_message(...)`, kind-conditional
   fragments (IG-372 ordering): continuation →
   `PLAN_CONTINUATION_DISCRIMINATE_FRAGMENT`; assess →
   `PLAN_ASSESS_INSTRUCTIONS_FRAGMENT`; gap →
   `PLAN_GAP_ANALYSIS_INSTRUCTIONS_FRAGMENT`; generate →
   `EXECUTION_POLICIES` + `PLAN_GENERATE_INSTRUCTIONS`.
   `build_response_language_hint()` appended.
4. **Human message assembly** — scenario builders in `user_message.py`:
   `build_plan_generate_message`, `build_plan_assess_message[_v2]`,
   `build_plan_gap_message`, `build_plan_continuation_message`. Goal text
   normalized by `_goal_text(goal)` (strips legacy `(iteration N/M)` suffix);
   sections ordered via `_render_sections([("GOAL", ...), ("EXECUTION TASK", ...),
   ("TASK", ...)])`; `goal_preview_text(goal)` (`planner_assembly.py`,
   120-char cap) feeds the envelope GOAL line; DAG context via
   `_format_dag_context` → `_render_dag_status`.
5. **Prior goals** (new_goal fallback): `context_bundle.prior_goals` or
   `_prior_goals_from_checkpoint(checkpoint, exclude_goal_id)` producing
   `PriorGoalSummary` rows from completed/cancelled/failed goal_history.
6. **Final composition**:
   ```
   [SystemMessage(system_content)]
     + projected ledger
     + parsed prior-conversation (USER/ASSISTANT XML → LoopHuman/AIMessage)
     + LoopHumanMessage(human_content, phase=plan_assess|plan_generate|plan_gap_analysis)
   ```

## 5. Shared Architecture Characteristics

1. **Two-tier SystemMessage + HumanMessage composition** — both tiers emit the
   same message-list shape; RFC-206 conformance confirmed.
2. **Cache optimization (IG-183 pattern)** — static fragments prefetched once
   at import in both `autopilot/prompts/fragments/__init__.py` and
   `sloop/prompts/fragments/__init__.py`. No per-call file reads.
3. **Volatility tiering** — static rubrics/JSON schemas/security rules in
   fragments (cache-stable); per-call facts via `.format` kwargs / builder args
   (dynamic). Aligns with RFC-214 volatility tiers.
4. **Structured output** — both tiers rely on Pydantic structured-output
   schemas (`GoalPlacementResponse`, Reason JSON) for parseable LLM returns.

## 6. Divergence Points (deliberate)

| Aspect | Autopilot | StrangeLoop |
|--------|-----------|-------------|
| Richness | Thin `render_*` → `.format` | Hierarchical `PromptBuilder` with projection |
| Prior conversation | Not assembled | XML parse → LoopHuman/AIMessage |
| Phase branching | By `analyze_*` method | By `PlannerCallKind` discriminator |
| Ledger projection | None | CE ledger slicing (Slice A) |
| Goal normalization | Direct passthrough | `_goal_text` suffix strip + 120-char preview |

## 7. Risk / Follow-up Observations

- **No defects identified** in traced paths; assembly matches RFC-206 and
  IG-736 design rules.
- **Duplicate `render_*` → `.format` pattern** across autopilot verify/backoff/
  consensus/maturity/rail is intentional (one-level module, IG-736) — not a
  refactor candidate.
- **`(iteration N/M)` suffix strip in `_goal_text`** is legacy compatibility
  surface; if legacy goal strings are fully migrated, the strip becomes dead
  code. Flag for future cleanse pass only after confirming no callers emit the
  suffix.

## 8. Reference Paths

| Component | Path |
|-----------|------|
| Autopilot render entry | `packages/soothe/src/soothe/autopilot/prompts/verify.py:96` |
| Autopilot roles | `packages/soothe/src/soothe/autopilot/prompts/roles.py` |
| Autopilot fragments | `packages/soothe/src/soothe/autopilot/prompts/fragments/__init__.py` |
| Autopilot envelopes | `packages/soothe/src/soothe/autopilot/prompts/envelopes.py` |
| Autopilot consumer | `packages/soothe/src/soothe/autopilot/verify/verifier_reasoner.py` |
| sloop builder | `packages/soothe/src/soothe/sloop/prompts/builder.py:86` |
| sloop user messages | `packages/soothe/src/soothe/sloop/prompts/user_message.py` |
| sloop planner assembly | `packages/soothe/src/soothe/sloop/prompts/planner_assembly.py` |
| sloop ledger projection | `packages/soothe/src/soothe/sloop/prompts/plan_ledger_projection.py` |
| sloop consumer | `packages/soothe/src/soothe/sloop/cognition/planner.py` |
