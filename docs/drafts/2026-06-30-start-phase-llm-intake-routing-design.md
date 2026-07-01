# Start-Phase LLM Intake & Branch Routing — Design Draft

> **Status**: Draft (brainstorm output, not yet an RFC)
> **Date**: 2026-06-30
> **Scope**: Improve the intelligence of user-goal handling in the start phase and reduce first-message response latency, before the first task is submitted to CoreAgent.

---

## 1. Problem & Goals

Today, the start-phase pipeline (user goal → first CoreAgent task) uses a mix of keyword/rule heuristics and LLM calls arranged sequentially. This has two problems:

1. **Heuristic judgment is unintelligent.** `IntentClassifier._is_likely_agentic` (`packages/soothe/src/soothe/foundation/sloop/intention/classifier.py:260`) classifies any query with `len > 80` chars, `> 15` words, or `≥ 2` newlines as `agentic` *without* consulting the LLM. A long trivia question ("What is the airspeed velocity of an unladen swallow, and how does it vary across swallow species in different wind conditions...?") is forced down the agentic path. The `simple_bypass` string-prefix match (`simple_bypass.py:28`, `startswith("I will complete this goal directly:")`) is similarly content-blind.

2. **First-message latency is high.** On a fresh first message, the critical path runs these LLM/IO steps strictly sequentially (none parallelized):
   - Intent classification LLM call (`_runner_strange_loop.py:447`)
   - `get_git_status` (`_runner_strange_loop.py:530`)
   - `state_manager.load()` checkpoint (`strange_loop.py:234`)
   - CE backend construct + `ce.load()` + `create_goal`/`activate_goal` (`strange_loop.py:416`–`502`)
   - Sync file reads: `load_project_instructions()`, `load_agent_instructions()`, `load_memory()` (`strange_loop.py:507`–`515`)
   - PlanGeneration LLM call (`planner.py:1297`)

   The fresh-loop shortcut (`bounded_evidence_gather.py:22`, IG-476) already removes the StatusAssessment LLM from the fresh path. The remaining blockers are the intent call, the pre-graph IO cluster, and the single plan call.

### Design principles (from the brainstorm brief)

1. Use an **LLM** instead of keyword-based heuristic judgment.
2. Optimize the starting phases: **intent classify**, **plan-access** (pre-graph IO), **plan-generate**.
3. Explore optimization strategies **before** submitting the first task to CoreAgent.
4. **Branch-based routing** driven by the LLM result.

### Central tension (the design's spine)

The two principles conflict if done naively: replacing `_is_likely_agentic` with an LLM call *adds* a sequential round-trip to every first message — and today that heuristic *saves* latency for long queries by skipping the LLM. The resolution is to **run the intake LLM in parallel with the pre-graph IO cluster** (which must run anyway), so the LLM costs ~zero added critical-path latency, then use its richer label to **skip whole phases** for easy goals. Intelligence goes up *and* latency goes down.

### Confirmed decisions (locked in brainstorm)

- **Latency scope**: Parallelize the intake LLM with pre-graph IO + branch routing + complexity-tiered planning. No speculative first-task emission, no plan-token streaming (deferred as a future aggressive variant).
- **Intake taxonomy**: Lean 4-class — `quiz | trivial | simple | complex`. Continuation is a **structural overlay** from checkpoint state (not an LLM label). Clarification **stays emergent** — the planner still routes to `await_clarification` when it cannot plan; it is not an intake branch.

---

## 2. Current State (verified from code)

### 2.1 Graph topology (`orchestrator/builder.py:56`)

Start-phase spine today:

```
START → init_or_resume
  → iteration_gate
  → iteration_start
  → bounded_evidence_gather   (fresh-loop routing, IG-476)
  → plan_assess | plan_generate
  → resolve_decision
  → validate_evidence_bindings
  → execute   (CoreAgent handoff)
```

All graph routing is **state-key based** (deterministic reads of string flags set by nodes). The only LLM-based routing today is (a) intent classification (pre-graph) and (b) inside `plan_assess`/the planner. There is **no keyword-based routing inside the graph** — the keyword heuristics live pre-graph in the intent classifier.

### 2.2 Routing functions (`orchestrator/routing.py`)

- `route_after_init` (line 51): `intent_route == "fast_path"` → END (quiz), else `iteration_gate`.
- `route_after_evidence_gather` (line 15): `evidence_gather_route == "plan_generate_skip_assess"` → `plan_generate` (fresh-loop skip), else `plan_assess`.
- `route_after_assess` (line 74): clarification / `goal_done` / `skip_generate` → `resolve_decision` / else `plan_generate`.
- `route_after_plan` (line 65): clarification / `goal_done` / else `resolve_decision`.

### 2.3 Intent classifier (`intention/classifier.py`)

- `classify_intent` (line 68): `intent_hint == QUIZ` short-circuit (line 89, structural, keep) → `_is_likely_agentic` heuristic bypass (line 93, **remove**) → single structured LLM call with one retry (line 103) → safe `agentic` fallback (line 226).
- LLM result schema: `IntentClassificationLLMResult` (`models.py:107`) — binary `quiz | agentic` + `task_complexity` + piggybacked `quiz_response`.
- Constructed with the **fast** model (`runner/__init__.py:131`).

### 2.4 Fresh-loop skip (`bounded_evidence_gather.py:22`, IG-476)

`_is_fresh_loop(ctx)` is a **structural state check** (iter 0, no step results, not continuation, no CE completed goals, no recovery). It is *not* a content heuristic. **Keep as-is** — replacing it with an LLM would add latency. It becomes an internal optimization of the `complex` branch.

### 2.5 Simple-query bypass (`planning/simple_bypass.py`)

`is_simple_query_direct_next_action` (line 28) matches a synthetic prefix string. The `task_complexity == "simple"` gate comes from the LLM label (good), but the bypass *detection* is a `startswith`. Replaced by the `trivial` branch (synthetic 1-step plan) + `simple` branch (lightweight plan).

### 2.6 Pre-graph IO cluster (`strange_loop.py:234`–`515`)

Runs sequentially after intent classification, before graph dispatch: checkpoint load, CE backend construct + load, `create_goal`/`activate_goal` DB writes, and three **synchronous** file reads (`load_project_instructions`, `load_agent_instructions`, `load_memory`) on the event loop. Plus `get_git_status` in the runner (`_runner_strange_loop.py:530`).

---

## 3. Design

### 3.1 Overview

Two coordinated changes:

1. **Pre-graph: parallelized intake.** Replace the binary intent LLM + heuristic bypass with a single **intake LLM** call (fast model) returning a 4-class label + complexity. Run it `asyncio.gather`-ed with the pre-graph IO cluster (checkpoint load, CE load, instructions/memory file reads, git status). The intake LLM is no longer on the sequential critical path — it overlaps IO that must run anyway.

2. **Graph: branch routing by intent.** Add a `route_by_intent` conditional edge after `init_or_resume` that dispatches to one of four branches based on the intake label (with continuation as a structural overlay). Each branch runs only the phases it needs:

```
                        ┌── quiz          → quiz executor → END
                        ├── trivial       → synth 1-step plan → resolve → validate → execute
init_or_resume → route_by_intent ───┼── simple         → lightweight plan_generate → resolve → validate → execute
                        ├── complex       → bounded_evidence_gather → plan_assess? → plan_generate → resolve → validate → execute
                        └── (continuation overlay, structural) → plan_assess(cont) → plan_generate → resolve → validate → execute

  # clarification stays emergent: plan_generate/plan_assess still route to await_clarification when they cannot plan
```

### 3.2 Intake LLM

**Schema** — extend `IntentClassificationLLMResult` (`models.py:107`) to a 4-class enum. Reuse the existing `TaskComplexity` enum (`models.py:27`, already has `minimal | simple | medium | complex`) so no new complexity vocabulary is introduced:

```python
class IntakeLabel(StrEnum):
    QUIZ = "quiz"            # greeting/thanks/trivia, no tools
    TRIVIAL = "trivial"      # single obvious action, no planning LLM needed
    SIMPLE = "simple"        # single focused step, lightweight plan
    COMPLEX = "complex"      # multi-step / multi-phase, full plan
```

**Prompt** — a new `intake_classification.xml` (replacing `intent_classification.xml`) instructing the LLM to pick one of the four labels and, for `quiz`, piggyback the answer in `quiz_response` (preserving the existing quiz short-circuit optimization). The boundary definitions:

- `quiz` — conversational, no tool execution (greetings, thanks, static trivia).
- `trivial` — one obvious tool call or direct answer; no decomposition needed (e.g., "what time is it?", "list files in this dir").
- `simple` — a single focused step with light planning (e.g., "read RFC-220 and summarize the topology").
- `complex` — multi-step, architectural, or multi-phase work needing full planning.

**Heuristic removal** — delete `IntentClassifier._is_likely_agentic` (`classifier.py:260`) and its call site (line 93). The `intent_hint == QUIZ` bypass (line 89) stays — it is a caller assertion, not a content heuristic.

**Retry & fallback** — keep the existing single-retry loop (line 103) and safe fallback. **Fallback label is `complex`** (not `agentic`): on intake failure, route to the full `complex` branch — the safest default because it runs the most capable pipeline. This preserves today's "fail safe = run the full loop" behavior.

**Model** — fast model (unchanged from today's `config.create_chat_model("fast")`).

### 3.3 Parallelized pre-graph IO

In `_run_strange_loop` (`_runner_strange_loop.py:397`), restructure the pre-graph sequence into a single `asyncio.gather`:

```python
# Pseudocode — actual code respects existing ordering constraints (see §3.6)
intake_task = self._intake_classifier.classify_intake(user_input, intent_hint=intent_hint)
checkpoint_task = state_manager.load()
git_task = get_git_status(workspace) if workspace else _none()
# CE load + create_goal depend on checkpoint result, so they run in a second stage
# (see §3.6 for the two-stage gather that preserves ordering)

intake, checkpoint, git_status = await asyncio.gather(intake_task, checkpoint_task, git_task)

# stage 2: CE construct + load + create_goal/activate_goal (needs checkpoint),
#          with instructions/memory file reads parallelized via to_thread
ce = await _hydrate_ce(checkpoint, ...)   # internally gathers ce.load + 3 file reads
```

**Async file reads** — `load_project_instructions()`, `load_agent_instructions()`, `load_memory()` (`strange_loop.py:510`–`513`) are sync today. Wrap each in `asyncio.to_thread(...)` and gather them with `ce.load()`. This removes three blocking disk reads from the event loop and lets them overlap the intake LLM round-trip.

**Result** — the intake LLM round-trip (~300–600 ms on the fast model) is hidden behind IO that previously added to the critical path sequentially. Net first-message latency on a fresh message drops by roughly one LLM round-trip minus the gather overhead.

### 3.4 Branch routing in the graph

**New state key** — add `intake_label: IntakeLabel` (and keep the existing `intent_route` for the quiz fast-path) to `LoopGraphState` (`orchestrator/state.py:21`).

**New routing function** — `route_by_intent(state, ctx)` in `routing.py`, wired as the conditional edge after `init_or_resume` (replacing the current two-valued `route_after_init`):

```python
def route_by_intent(state: dict[str, Any], ctx: LoopRuntimeContext) -> str:
    # Structural continuation overlay: checked from checkpoint state, not the LLM label.
    if ctx.continue_loop_mode and _has_prior_completed_goal(ctx):
        return "plan_assess"          # continuation branch (existing path)
    label = state.get("intake_label")
    if label == "quiz":
        return END                    # quiz executor handled pre-graph; defensive duplicate
    if label == "trivial":
        return "resolve_decision"     # synth plan injected in init_or_resume
    if label == "simple":
        return "plan_generate"        # skip bounded_evidence_gather + plan_assess
    return "bounded_evidence_gather"  # complex: full existing spine
```

**`init_or_resume` node change** — `node_init_or_resume` (`init_or_resume.py:18`) reads the pre-graph intake result from `ctx.loop_state.intent`, sets `intake_label` on the graph state, and for the `trivial` branch injects a minimal single-step `PlanResult` into `ctx.scratch` (shape defined in §3.5.1 — goal as the step action, no synthetic reasoning text).

**Branch wiring** (`builder.py:117`):

```python
graph.add_edge(START, "init_or_resume")
graph.add_conditional_edges(
    "init_or_resume",
    route_by_intent,
    {
        "iteration_gate": "iteration_gate",          # legacy quiz defensive
        "bounded_evidence_gather": "bounded_evidence_gather",  # complex
        "plan_generate": "plan_generate",            # simple
        "plan_assess": "plan_assess",                # continuation
        "resolve_decision": "resolve_decision",      # trivial (synth plan in scratch)
        END: END,                                    # quiz
    },
)
```

The `complex` branch then runs the **existing** spine unchanged: `bounded_evidence_gather` (with its IG-476 fresh-loop skip intact) → `plan_assess?` → `plan_generate` → `resolve_decision` → `validate_evidence_bindings` → `execute`. No change to the complex path's internals.

### 3.5 Complexity-tiered planning

| Branch | Plan LLM call | Notes |
|---|---|---|
| `quiz` | none | Handled pre-graph by `_run_quiz` (unchanged). |
| `trivial` | none | Minimal 1-step plan injected by `init_or_resume` (§3.5.1). Skips `plan_generate` entirely. Replaces `simple_bypass` string-prefix detection with an LLM label. |
| `simple` | **lightweight** plan call | `plan_generate` runs, but with a stripped plan context/prompt (no evidence-gather round, fewer history slots). Same `PlanGeneration` schema, cheaper prompt. |
| `complex` | **full** plan call | Existing `generate_from_assessment` (`planner.py:1297`) unchanged. |
| `continuation` | full plan call | Existing `assess_continuation` (`planner.py:814`) → `plan_generate`. Unchanged. |

**Lightweight plan** — `plan_generate` reads `ctx.loop_state.intent.task_complexity`; when `simple`, it calls a new `plan_phase.generate_lightweight(...)` that reuses `generate_from_assessment`'s structured-output path but with a smaller context window (last N step results, no full evidence ledger). This is the one new planner method.

#### 3.5.1 Trivial-branch plan shape (no synthetic reasoning message)

The legacy `simple_bypass` (`planning/simple_bypass.py`) bundles two concerns. Only one survives:

- **`SIMPLE_QUERY_DIRECT_PREFIX`** (`"I will complete this goal directly:"`) — a verbose prefix prepended to the goal to form the step's `next_action`. **Deleted.** Under LLM routing the trivial label comes from the intake LLM; the prefix existed only so `is_simple_query_direct_next_action` (a `startswith` detector) could recognize the synthetic plan in the legacy path. With the label authoritative, both the prefix and the string detector are dead weight.
- **`SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT`** (the `## Result` block contract) — **kept.** This is functional, not cosmetic: it's an `expected_output` hint placed in the step's user message that forces the assistant to restate concrete data (numbers, paths, names) so `plan_assess` recognizes completion on the next iteration. It adds no LLM call and no user-visible text.

The trivial branch therefore synthesizes a **minimal plan object**, not a synthetic *reasoning message*:

- Step action: the intake LLM's normalized `goal_description` (fallback: the raw user goal). No prefix.
- Step `expected_output`: the `## Result` contract (moved to a shared helper, e.g. `planning/trivial_plan.py`).
- Plan reasoning: `None` / empty — the loop does not narrate "I will complete this directly" to the user. The user sees the goal they typed and then the executed result, nothing in between.

The 1-step `Decision` indirection is retained because `Executor` (`executor.py:180`) consumes a structured decision (step ids allocated by `resolve_decision`, plan ingested by `plan_manager.ingest_plan` at `resolve_decision.py:82`) — CoreAgent cannot take a bare goal string. So the branch builds the minimum structured plan the executor accepts, with no synthetic prose.

This polish is exactly the kind of cleanup the brainstorm brief called for: the prefix was a heuristic artifact (string-prefix detection) that LLM routing renders obsolete. Removing it makes the trivial branch emit the goal itself as the step, which is both less verbose and more honest.

### 3.6 Ordering constraints (critical for correctness)

The two-stage gather must respect real dependencies:

- **Stage 1 (parallel, no deps)**: intake LLM, `state_manager.load()`, `get_git_status()`.
- **Stage 2 (needs checkpoint)**: CE backend construct + `ce.load()` + `create_goal`/`activate_goal` (these branch on `checkpoint.status`, `strange_loop.py:234`–`359`).
- **Stage 2 (parallel within stage)**: the three instruction/memory file reads (wrapped in `to_thread`) gather with `ce.load()`.

The intake LLM result is consumed only at `init_or_resume` (graph time), so it can be produced any time during stages 1–2. The `LoopRuntimeContext` is assembled at `strange_loop.py:535` after stage 2 completes; the intake result is stored on `loop_state.intent` exactly as today.

### 3.7 What stays unchanged

- **Fresh-loop skip** (`bounded_evidence_gather.py:22`) — internal to the `complex` branch.
- **Clarification relay** (`await_clarification`, RFC-622) — stays emergent from `plan_generate`/`plan_assess`; not an intake branch.
- **Continuation detection** — structural from checkpoint `goal_history` (`strange_loop.py:234`–`359`), not an LLM label.
- **Quiz short-circuit** — pre-graph in the runner (`_runner_strange_loop.py:469`), piggybacked answer preserved.
- **CoreAgent handoff** — `node_execute` → `Executor` (`execute_steps.py:494`) unchanged.

---

## 4. Data Flow (end-to-end)

```
user goal
  │
  ▼
_run_strange_loop
  │
  ├─ stage 1 gather ─┬─ intake LLM (fast model, 4-class)
  │                   ├─ state_manager.load()
  │                   └─ get_git_status()
  │
  ├─ stage 2 gather ─┬─ CE construct + ce.load()
  │                   ├─ create_goal / activate_goal  (needs checkpoint)
  │                   └─ to_thread: project/agent instructions, memory
  │
  ▼
StrangeLoop.run_with_progress → graph.ainvoke
  │
  ▼
init_or_resume   (sets intake_label; trivial → inject synth plan into scratch)
  │
  ▼
route_by_intent
  ├─ quiz          → END (handled pre-graph)
  ├─ trivial       → resolve_decision → validate → execute
  ├─ simple        → plan_generate(lightweight) → resolve → validate → execute
  ├─ complex       → bounded_evidence_gather → plan_assess? → plan_generate(full) → resolve → validate → execute
  └─ continuation  → plan_assess(cont) → plan_generate → resolve → validate → execute
```

---

## 5. Error Handling

- **Intake LLM failure** — after the single retry, fallback label = `complex`. The full pipeline runs. Logged with error context (preserves today's `_fallback_intent` pattern).
- **IO gather failure** — each IO task is wrapped; partial failures degrade gracefully exactly as today (e.g., `git_status = None` on failure, `_runner_strange_loop.py:534`). The gather uses `return_exceptions=True` where a task failure should not abort the others.
- **Mislabel risk** — a `trivial` goal mislabeled as `complex` pays an extra plan call (latency cost, no correctness loss). A `complex` goal mislabeled as `trivial` produces a 1-step plan that the loop's existing post-execution `plan_assess` will catch on the next iteration (the loop replans). The design leans conservative: the intake prompt explicitly errs toward `complex` when uncertain.
- **Synthetic plan failure (trivial branch)** — if `init_or_resume` cannot build the synth plan, it sets `intake_label = "complex"` and falls through to the full spine.

---

## 6. Testing

- **Intake classifier unit tests** — golden-set queries per label (including the long-trivia case that today's heuristic misroutes). Assert the LLM is called for all queries (no heuristic bypass).
- **Routing unit tests** — `route_by_intent` truth table over `(label, continue_loop_mode, has_prior_completed_goal)`.
- **Parallelization tests** — assert `intake`, `checkpoint.load`, `git_status` run concurrently (mock with `asyncio.Event` latches). Assert file reads go through `to_thread`.
- **Branch integration tests** — one fixture per branch: assert the visited node sequence matches §3.4 (e.g., `trivial` skips `plan_generate`; `simple` skips `bounded_evidence_gather` and `plan_assess`).
- **Latency regression test** — a timing-based test with generous bounds (flaky-resistant) asserting a fresh `complex` first-message does not exceed today's p95 by more than the gather overhead. Gate behind a marker so it can be skipped in CI if it proves flaky.
- **Mislabel recovery test** — force `trivial` on a multi-step goal; assert the loop replans on iteration 2 via `plan_assess`.

Tests live in `packages/soothe/tests/unit/` and `tests/integration/` per the project convention.

---

## 7. Migration & Rollout

- **Feature flag** — `config.agent.loop.intake.branch_routing.enabled` (default `false` initially). When off, the runner uses the legacy binary intent classifier and the graph uses `route_after_init`. When on, the new intake + `route_by_intent` path is active. This allows staged rollout and A/B comparison.
- **Config sync** — `config/config.template.yml` and `config/develop/config.yml` both updated (per project rule).
- **Removal of `simple_bypass`** — once the `trivial` branch is stable, the `SIMPLE_QUERY_DIRECT_PREFIX` string and `is_simple_query_direct_next_action` detector are deleted outright; the `## Result` `expected_output` contract is extracted to a shared `planning/trivial_plan.py` helper used by `init_or_resume` (trivial) and the legacy path during the flag transition. The verbose prefix does not survive — the trivial branch emits the goal itself as the step action (§3.5.1).
- **No wire-protocol change** — no daemon/event envelope impact; this is internal to the loop. (Memory note: Protocol-1 is the current wire standard; this design does not touch it.)

---

## 8. Components & Boundaries (isolation summary)

| Unit | Responsibility | Depends on | Consumed by |
|---|---|---|---|
| `IntentClassifier.classify_intake` | 4-class LLM intake | fast model, intake prompt | `_run_strange_loop` (stage 1 gather) |
| `route_by_intent` | branch dispatch by label + continuation overlay | `LoopGraphState.intake_label`, `ctx.continue_loop_mode` | `builder.py` conditional edge |
| `node_init_or_resume` (extended) | set `intake_label`; inject synth plan for `trivial` | `ctx.loop_state.intent`, `simple_bypass` helper | graph |
| `plan_phase.generate_lightweight` | cheaper plan call for `simple` | `PlanGeneration` schema, reduced context | `node_plan_generate` |
| `_run_strange_loop` (restructured) | two-stage parallel IO gather | `state_manager`, CE, `get_git_status`, intake | runner |

Each unit has one purpose and can be tested independently. The routing function is pure (testable without an LLM). The intake classifier is the only unit that calls an LLM.

---

## 9. Out of Scope

- **Speculative first-task emission** (emit a best-guess task from the intake skeleton before the full plan completes) — deferred to a future "aggressive" variant; adds cancel/reconcile machinery and UX risk.
- **Plan-token streaming to the user as draft** — deferred; perceived-latency win only, no intelligence change.
- **Embedding-based pre-filter** (A5 from the brainstorm) — deferred; needs a labeled-example index, not worth the complexity yet.
- **Post-execution failure-intent classifier** (`failure_intent_classifier.py`) — out of scope; not in the start phase.
- **`_pre_stream_planning` legacy path** — confirmed not on the current start path; left untouched (possible future cleanup).

---

## 10. Open Questions (to resolve during RFC/impl)

1. **Lightweight plan prompt scope** — exactly which context slots to drop for `simple`. Proposal: drop evidence-ledger history beyond the last 2 step results, drop the full prior-goal context. Confirm with a planning-quality eval.
2. **Feature-flag default timeline** — when to flip `branch_routing.enabled` to `true` in `develop`. Propose: after the branch integration tests pass and one week of A/B latency data.
3. **Intake prompt boundary calibration** — the `trivial` vs `simple` vs `complex` boundary is the main mislabel surface. Needs a small golden set (per §6) to lock the definitions before impl.
