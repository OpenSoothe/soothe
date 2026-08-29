# IG-769: Simplify `decompose_task` — Remove Evidence Collection

**RFC**: RFC-904 (Sloop Recursive Step Decomposition)
**Design draft**: `docs/drafts/2026-08-29-decompose-task-simplification-design.md`
**Scope**: `packages/soothe/` (sloop decompose + westworld middleware + executor + prompts + tests)

## Problem

The `decompose_task` tool carries an expensive hallucination-defense apparatus (the "d15f defense", schemes 2c + 2d): every tool call in a step thread is intercepted, classified as grounding-or-not, and its output captured into a corpus; each `decompose_task` call can trigger up to two FAST-model LLM calls (subtask auto-generation + grounding critic). The machinery required a mutable-list-in-a-ContextVar hack to survive LangGraph's `copy_context()` snapshots.

The cost (every tool call taxed, up to two FAST round-trips per decompose, Pregel-snapshot plumbing) is no longer worth it. The main model self-grounds well enough via prompt guidance, and the executor's `read_only_streak_limit` hard stop already backstops stuck gathering. The grounding apparatus grew during P1 implementation beyond what RFC-904 normatively specified — the RFC update makes the simpler posture normative.

## Solution

The tool becomes a pure validation-and-enqueue step. **Trust + guide, don't enforce**: accept explicit subtasks, enforce the branch cap (truncate, not reject), queue the proposal. No LLM calls inside the tool, no evidence tracking, no gates. Prompts still *guide* the model toward grounding (look before you split) as self-hygiene, but nothing *enforces* it with a gate.

## Changes

### DELETE `packages/soothe/src/soothe/sloop/decompose/grounding_guard.py`
Entire module (~360 lines). Every symbol is dead — verified no surviving reader:
`GroundingVerdict`, `UngroundedClaim`, `GeneratedSubtask`, `GeneratedSubtaskList`,
`check_proposal_grounded`, `generate_subtasks_via_fast_model`,
`build_no_evidence_guidance`, `build_ungrounded_claims_guidance`,
`_GENERATE_PROMPT`, `_CRITIC_PROMPT`, `_render_proposal`, `_render_evidence`.

### `packages/soothe/src/soothe/sloop/decompose/tool.py` (~180 → ~70 lines)
- Make `subtasks` **required** on `_DecomposeTaskArgs` (drop `None` default).
- Delete `_FAST_MODEL_KEY` / `_SOOTHE_CONFIG_KEY` constants.
- Delete `_build_proposal` helper (auto-gen branch + FAST-model call).
- Delete both gates: `current_evidence_calls() == 0` check, `check_proposal_grounded()` call.
- Delete all `grounding_guard` imports; drop `build_no_evidence_guidance` / `build_ungrounded_claims_guidance` / `generate_subtasks_via_fast_model` / `check_proposal_grounded` / `current_evidence_calls` / `current_evidence_corpus` imports.
- `_arun_decompose_task`: validate+parse subtasks → enforce branch cap (truncate) → wrap in `DecompositionProposal` → append to sink → return terminal message. No `conf.get` for `fast_model`/`soothe_config`/`goal_trace`.
- `_run_decompose_task` (sync): same logic, minus `async`.
- Keep `_resolve_max_branch_root` (still reads `soothe_max_branch_root`).
- Keep `task` arg (cheap context; removing it changes the schema for no benefit).
- Branch cap: **truncate** to `max_branch_root`, not reject. Return message reflects post-truncation count.

### `packages/soothe/src/soothe/sloop/decompose/runtime.py` (~184 → ~55 lines)
- Delete: `_evidence_calls`, `_evidence_corpus`, `_evidence_counter`, `_evidence_corpus_list`, `record_evidence_call`, `record_evidence_output`, `current_evidence_calls`, `current_evidence_corpus`, `_EVIDENCE_EXCERPT_CAP`.
- Slim `DecomposeRuntimeTokens` to `step` / `wave` / `sink` (drop `evidence` / `evidence_corpus`).
- Slim `bind_decompose_runtime` / `reset_decompose_runtime` to match.
- Keep: `_current_step_id`, `_wave_seq`, `_proposal_sink`, `current_step_id`, `current_wave_seq`, `current_proposal_sink`, `langgraph_configurable`.
- The mutable-list ContextVar hack + its comment go — only the counter needed it. Remaining contextvars are set-once / reset-once.

### `packages/soothe/src/soothe/sloop/decompose/middleware.py`
- Delete from `awrap_tool_call` / `wrap_tool_call`: `_is_grounding_call`, `_GROUNDING_TOOL_NAMES`, `_extract_result_text`, the `record_evidence_call()` + `record_evidence_output()` calls, the counting comments.
- What remains in the tool-call hooks: the plan/ask stray-call interception (passthrough for non-`decompose_task` calls; guidance `ToolMessage` for `decompose_task` in plan/ask modes).
- `modify_request` (model-call injection): untouched — tool injection/stripping, system-prompt addenda, branch-cap message.

### `packages/soothe/src/soothe/sloop/middleware/westworld.py`
- Delete `_WESTWORLD_ESCALATION_EVIDENCE_THRESHOLD` (constant = 10).
- Delete the escalation block in `modify_request`: the `current_evidence_calls()` read, `current_proposal_sink()` read, threshold check, `WESTWORLD_ESCALATION_ADDENDUM` append.
- `modify_request` becomes: guard (step id / mode) → match triggers → append fan-out addendum.
- Drop `WESTWORLD_ESCALATION_ADDENDUM` from the `soothe.prompts` import.
- Keep `_match_triggers` → `WESTWORLD_FANOUT_ADDENDUM` (phrase → addendum, no counter).

### `packages/soothe/src/soothe/sloop/engine/execute/executor.py` (lines ~2077-2086)
- **Strip** the `if self._fast_model is not None: configurable["fast_model"] = ...` block + its "RFC-904" comment. No surviving step-thread reader of `configurable["fast_model"]`.
- **Strip** the `if self._goal_trace is not None: configurable["goal_trace"] = ...` block. No surviving step-thread reader of `configurable["goal_trace"]` (the executor uses `self._goal_trace` directly for Langfuse callback merging, not via the configurable).
- **Keep** the `soothe_config` block — live consumer at `soothe_nano/middleware/filesystem.py:298` (virtual-mode + max-file-size). Update its comment to reflect its real purpose (nano filesystem middleware), not "grounding critic".

### DELETE `packages/soothe/src/soothe/prompts/fragments/decompose/westworld_escalation_addendum.xml`
- Remove `WESTWORLD_ESCALATION_ADDENDUM` export from `prompts/fragments/__init__.py` (line 49, 66) and `prompts/__init__.py` (line 47, 75).

### `packages/soothe/src/soothe/prompts/fragments/decompose/decompose_task_tool.xml`
- Delete the "Auto-generation mode" section (lines 18-28).
- Delete the "Ground your subtasks in evidence" section (lines 29-35).
- Update the Args line: `subtasks` is now required; drop the "When subtasks is omitted" sentence.
- Keep the branch-cap paragraph (update: excess → truncated, not rejected).

### `packages/soothe/src/soothe/prompts/fragments/decompose/parallel_nudge_addendum.xml`
- Lines 12-13: "proposals citing files or directories that do not exist will be rejected" → advisory: "proposals citing areas you have not confirmed waste child-thread budget if wrong — confirm areas first." Keep the "gather one broad search first" guidance.

### `packages/soothe/src/soothe/prompts/fragments/decompose/westworld_fanout_addendum.xml`
- Line 10: same replacement — "will be rejected" → "waste child-thread budget if wrong."

### Tests

#### DELETE `packages/soothe/tests/unit/core/loop/decompose/test_grounding_guard.py`
Tests a deleted module.

#### REWRITE `packages/soothe/tests/unit/core/loop/decompose/test_decompose_task_tool.py`
- Remove: evidence-call setup, zero-evidence rejection test, critic rejection/acceptance tests, `copy_context` counter-survival test.
- Keep: `queues_proposal`, `errors_without_runtime`, `execute_envelope_is_instance_focused`.
- Add: one test asserting branch-cap truncation (propose >cap, assert truncated count + return message).

#### REWRITE `packages/soothe/tests/unit/core/loop/decompose/test_decompose_middleware.py`
- Remove: evidence-capture assertions (`record_evidence_call` / `record_evidence_output` mocks).
- Keep: tool-injection/stripping/mode-guard tests.

#### REWRITE `packages/soothe/tests/unit/middleware/test_westworld_middleware.py`
- Remove: `_patch_runtime` helper + three escalation tests (`test_escalation_after_evidence_threshold`, `test_no_escalation_below_threshold`, `test_no_escalation_when_proposal_queued`).
- Keep: fan-out phrase-trigger tests.

## Verification

- `ruff check` + `mypy` on edited packages.
- `pytest packages/soothe/tests/unit/core/loop/decompose/ packages/soothe/tests/unit/middleware/test_westworld_middleware.py`
- Grep-confirm no dangling references: `grep -rn "grounding_guard\|current_evidence_calls\|record_evidence_call\|record_evidence_output\|current_evidence_corpus\|check_proposal_grounded\|generate_subtasks_via_fast_model\|build_no_evidence_guidance\|build_ungrounded_claims_guidance\|WESTWORLD_ESCALATION" packages/soothe/src/ packages/soothe/tests/` returns only intentional mentions (change-history comments).

## Risk

The grounding gates were a hallucination defense. Without them, a model that proposes subtasks citing non-existent files wastes child-thread context budget before the fabrication is discovered — one wasted budget per bad proposal, discovered when the child thread fails to find the cited path. The bet: the main model self-grounds well enough (via retained prompt guidance + its own tool usage) that the gates' rejection rate wasn't worth their overhead. The sole remaining stuck-gathering backstop is the executor's `read_only_streak_limit` hard stop.
