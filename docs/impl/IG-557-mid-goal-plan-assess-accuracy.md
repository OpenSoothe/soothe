# IG-557: Mid-Goal Plan-Assess Accuracy

**RFCs**: RFC-214 (ledger projection), RFC-220 (loop graph), RFC-227 (prior progress digest), RFC-630 (intake routing)
**Created**: 2026-07-07
**Status**: Draft
**Related**: IG-555 (iter=0 prior-completion bias), IG-538 (unified planner assembly), IG-542 (execute Slice A), IG-551 (continuation coordination)
**Motivating observation**: After the first execution wave, plan-assess can return `goal_progress="complete"` and route to goal completion despite incomplete multi-part goals — especially on continuation goals where Slice A prior `goal_completion` tone dominates current-wave evidence.

---

## Executive Summary

IG-555 mitigated prior-goal completion anchoring at **iter=0** (boundary marker + complex undersized-plan guardrail). The same failure mode persists at **mid-goal** (`iteration ≥ 1`, or iter=0 with `step_results`): assess sees prior goal completion in Slice A, strips its own prior assess ledger, and may prematurely declare the current goal complete.

**Solution** (phased):

1. **Assess prompt noise optimization** — dedicated assess-only projection + minimal task envelope (see § High-Accuracy Prompt Architecture)
2. **Assess-specific ledger projection** — omit Slice A and non-evidence phases for `call_kind=assess`
3. **Mid-goal execution-evidence guard** — reject `goal_progress=complete` when complex intake lacks sufficient current-goal execution evidence
4. **Inline last-assessment envelope** — compact routing continuity without prior assess ledger pairs
5. **Plan-gap-analysis (Phase E)** — optional pre-assess pass mapping evidence → goal components → distance from goal
6. **Optional**: hint-vs-LLM disagreement override (telemetry today only)

---

## Background: When Plan-Assess Runs

Plan-assess (`node_plan_assess`) is invoked from the StrangeLoop graph on these paths:

| Trigger | Condition |
|---------|-----------|
| **Complex fresh goal** | `bounded_evidence_gather → plan_assess` (unless IG-476 fresh-loop skip → `plan_generate`) |
| **Continuation + trivial** | `init_or_resume → plan_assess` (continuation discriminator) |
| **Every post-wave cycle** | `execute → record_iteration → iteration_gate → iteration_start → bounded_evidence_gather → plan_assess` |
| **Clarification resume** | `await_clarification` with `last_clarification_origin=plan_assess` |

**Skipped**:

- Simple intake → `plan_generate` directly
- Trivial intake → pseudo 1-step plan → `resolve_decision`
- Continuation + simple/complex → evidence gather (assess after gather, not continuation discriminator)
- Fresh-loop bypass (IG-476) at iter=0 with no prior CE goals

After assess, routing (`route_after_assess`):

- `plan_route=goal_done` → `goal_completion`
- `assess_route=continue_generate` → `plan_generate`
- `assess_route=skip_generate` → `resolve_decision` (continuation bootstrap only)

---

## Background: Messages Projected into Plan-Assess

Built by `PromptBuilder.build_plan_messages(..., plan_phase="assess")` → `LLMPlanner.assess_status()`.

### Prompt assembly order

```
1. SystemMessage     — plan_assess_instructions.xml (+ memory, follow-up policy)
2. Projected ledger  — native Human/AI turns (phase-filtered, tail-capped)
3. Task envelope     — LoopHumanMessage: GOAL / CONTEXT sections / TASK
```

### Projection mode

```python
# resolve_planner_projection_mode(state)
new_goal  if iteration == 0 and not step_results
mid_goal  otherwise
```

### Mid-goal ledger (`_project_planner_ledger_mid_goal_isolated`)

| Slice | Content | Phases |
|-------|---------|--------|
| **Slice A** | Up to `cross_goal_completion_tail` (default 3) prior **goal** completions | `goal_completion` H/A, compacted + IG-555 boundary on human |
| **Current segment** | From after last prior `goal_completion` AI | `intent_classify`, `plan_generate`, `execute_step` |

**Excluded from all plan-assess projections**:

- All `plan_assess` pairs (assess never sees prior assess reasoning in ledger)
- Prior goal `execute_step` rows (isolated to current goal segment)

**Caps**: `plan_prompt_ledger.plan_ledger_max_messages` (default 40 tail messages).

### Task envelope sections (`build_plan_assess_message`)

| Section | Mid-goal behavior |
|---------|-------------------|
| `GOAL` | Full goal text |
| `PRIOR GOALS` | Compact metadata from ContextBundle |
| `GOAL LINEAGE` | When not redundant and no completion in ledger |
| `PRIOR PROGRESS` | RFC-227 per-wave digest from executor; omitted if stale (`prior_progress.iteration < current_iteration - 1`) |
| `DAG STATUS` / `STEP LINEAGE` / `SKILL` | When present |
| `TASK` | Assess status / goal_progress / assessment_reasoning |

Unlike plan-generate, assess does **not** receive an inline `ASSESSMENT:` block from the current wave's prior assess call.

### Post-call ledger write

Assess records compacted human + full `StatusAssessment` AI dump with `phase=plan_assess`. These rows are excluded from subsequent projections.

---

## Problem Statement

### Failure chain (mid-goal)

```
Wave 1 executes successfully on undersized or partial plan
    ↓
record_iteration → iteration_gate → bounded_evidence_gather → plan_assess
    ↓
Projection mode = mid_goal
    ↓
Slice A: prior goal_completion ("completed successfully", recommended actions)
Current segment: current execute_step evidence (may be thin)
    ↓
Assess LLM: pattern-matches completion tone → goal_progress="complete"
    ↓
node_plan_assess routes to goal_completion (no IG-555 guard at iter>0)
    ↓
Multi-part goal terminates early
```

### Root causes

| Cause | Detail |
|-------|--------|
| **Slice A at assess** | Prior goal completion AI retains completion semantics; IG-555 boundary is on human envelope only |
| **Assess amnesia** | Prior `plan_assess` pairs stripped; model cannot see its own prior assessment chain |
| **Guardrail gap** | IG-555 guards only `iteration == 0` + complex intake before `goal_progress=complete` routing |
| **Hint ignored** | `_log_prior_progress_disagreement` is telemetry-only |
| **Ledger tail loss** | Default 40-message cap may drop early-wave execute evidence on long goals |

### Why IG-555 is insufficient

| IG-555 intervention | Mid-goal gap |
|---------------------|--------------|
| Boundary marker on goal_completion human | AI completion body still carries "done" narrative |
| Undersized-plan guard at iter=0 | No guard when `iteration ≥ 1` |
| Complex intake replan at iter=0 | Mid-wave assess can still return `complete` after partial execution |

---

## High-Accuracy Plan-Assess Prompt Architecture (Design View)

Design target: **one routing decision** (`StatusAssessment`) grounded on **current-goal evidence only**. Everything else is either excluded or reduced to a compact, non-directive summary.

### Design principles

| # | Principle | Implication |
|---|-----------|-------------|
| P1 | **Evidence over intent** | Assess sees execute outcomes + gap/progress summaries — not plans, intake labels, or prior goal completions |
| P2 | **Single GOAL authority** | Exactly one full `GOAL:` in the task envelope; no duplicates, no 120-char preview truncation |
| P3 | **No completion tone from other goals** | Zero prior `goal_completion` rows in assess projection (Slice A disabled) |
| P4 | **No plan-as-progress** | No `plan_generate` AI JSON in assess projection; plan scope ≠ goal scope |
| P5 | **Structured continuity** | Prior routing via compact inline blocks, not replayed assess ledger pairs |
| P6 | **Explicit denylist** | Blocks that are “usually absent” today remain **hard excluded** even when `ContextBundle` / `dag_context` are available |
| P7 | **Gap before route** (Phase E) | Optional `PlanGapAnalysis` inline block is the only “prior work” narrative besides evidence |

### Target message stack

```
┌─────────────────────────────────────────────────────────────────┐
│ SystemMessage (static, cache-stable)                            │
│   PLAN_ASSESS instructions only                                 │
│   + RESPONSE_LANGUAGE_HINT                                      │
│   ✗ MEMORY_INSTRUCTIONS  ✗ FOLLOW_UP_POLICY  ✗ EXECUTION_POLICIES │
├─────────────────────────────────────────────────────────────────┤
│ Projected ledger (assess-specific filter)                       │
│   mid_goal:  execute_step AI pairs only (see below)             │
│   new_goal:  empty OR last wave execute_step AI if in-flight     │
│   ✗ goal_completion  ✗ intent_classify  ✗ plan_generate         │
│   ✗ plan_assess  ✗ plan_gap_analysis  ✗ prior conversation    │
├─────────────────────────────────────────────────────────────────┤
│ Task envelope (single LoopHumanMessage, phase=plan_assess)      │
│   GOAL              (always full text)                          │
│   GAP ANALYSIS      (Phase E; when mid_goal)                   │
│   PRIOR PROGRESS    (refined digest; mid_goal only)             │
│   PREVIOUS ASSESSMENT (Phase C; when previous_plan present)     │
│   PLAN COVERAGE     (deterministic: remaining steps vs GOAL)    │
│   TASK              (routing instruction only)                  │
│   ✗ all other sections (explicit denylist below)                │
└─────────────────────────────────────────────────────────────────┘
```

### System tier — include / exclude

| Block | Current | Target | Reason |
|-------|---------|--------|--------|
| `plan_assess_instructions.xml` | ✅ | ✅ | Core contract |
| `RESPONSE_LANGUAGE_HINT` | ✅ | ✅ | Cache-stable, low noise |
| `MEMORY_INSTRUCTIONS` | Sometimes (bundle) | **✗ Always off** | Not evidence; belongs on execute |
| `FOLLOW_UP_POLICY` | When `recent_messages` | **✗ Always off** | Assess uses ledger/digest, not chat replay |
| `EXECUTION_POLICIES` | Generate only | **✗ Off** | Planning policy, not assessment |

Implementation: `build_plan_messages(..., call_kind="assess")` forces `context_bundle=None` for system assembly (memory block suppressed regardless of caller).

### Ledger projection — assess-specific filter

New function: `project_planner_ledger_for_assess(loop_messages, state, ledger_cfg)`.

#### Phase allowlist (strict)

| Phase | mid_goal (has execution) | new_goal (iter=0, no execution) |
|-------|--------------------------|----------------------------------|
| `execute_step` **AI only** | ✅ All current-goal segment | ✅ If in-flight execute ledger exists |
| `execute_step` **Human** | **✗** | **✗** |
| `goal_completion` (Slice A) | **✗** | **✗** |
| `intent_classify` | **✗** | **✗** |
| `plan_generate` | **✗** | **✗** |
| `plan_assess` | **✗** | **✗** |
| `plan_gap_analysis` | **✗** (inline only) | **✗** |

**Execute AI compaction** (projection-time, not ledger mutation):

```python
def _compact_execute_ai_for_assess(msg: BaseMessage) -> BaseMessage:
    """Keep outcome prose + tool-result excerpt; strip planning boilerplate."""
    # Prefer: last 400 chars of substantive text, or outcome_summary if tagged
    # Drop: repeated GOAL echoes, WORKSPACE blocks, INSTRUCTIONS sections
```

**Tail cap**: Prefer `plan_assess_ledger_max_messages` (new config, default **24**) over shared `plan_ledger_max_messages` (40) — assess needs recent evidence, not full history.

#### Noise removed vs current projection

| Removed block | Prior confusion |
|---------------|-----------------|
| Slice A `goal_completion` AI | “Completed successfully” / recommended actions |
| `plan_generate` AI JSON | Plan `reasoning` read as progress; step count ≠ goal scope |
| `intent_classify` JSON | Duplicate goal/intake framing |
| `execute_step` Human | Instruction-heavy; not evidence |
| Ledger omission banner | Drops early evidence silently — replace with **head+tail** keep (first + last N execute AI) |

### Task envelope — allowlist and denylist

#### Allowed sections (strict order)

```text
GOAL:
<full goal text — never truncated preview>

GAP ANALYSIS:          # Phase E; omitted when gap node skipped
<inline PlanGapAnalysis render>

PRIOR PROGRESS:        # mid_goal only; omitted at first assess
<refined digest — see below>

PREVIOUS ASSESSMENT:   # Phase C; omitted when no previous_plan
Status: continue | replan | done
Progress: none | low | medium | high | complete
Reasoning: <one line from previous_plan, ≤120 chars>

PLAN COVERAGE:         # deterministic code block; always when current_decision exists
completed_steps: 2/5
remaining_step_ids: 03, 04, 05
ready_steps: 03
note: Plan remaining ≠ goal complete; judge GOAL against evidence.

TASK:
Assess goal completion for GOAL only. Return status, goal_progress,
assessment_reasoning. Cite execute evidence and GAP ANALYSIS if present.
Do not treat plan step count or prior goals as completion proof.
```

#### Explicit denylist (hard exclude for `call_kind=assess`)

These are **never** rendered in the assess envelope, even when data is available:

| Section | Why excluded |
|---------|--------------|
| `PRIOR GOALS` | Prior-goal narrative; Slice A replacement — use gap analysis instead |
| `GOAL LINEAGE` | Parent-chain context; confuses “which goal am I judging?” |
| `STEP LINEAGE` | Plan reasoning history; plan-as-progress bias |
| `DAG STATUS` | Plan graph stats; “2/5 steps done” ≠ goal satisfied |
| `STEP ANCHOR REGISTRY` | Generate-only cross-wave dependency grounding |
| `STEP ID HINT` | Generate-only |
| `SKILL REFERENCE` | Execute grounding; not assess evidence (skill already applied) |
| `INTENT` / intake scope | Code-driven routing; not progress evidence |
| `ASSESSMENT` inline (current wave) | Assess must not see pre-baked answer |
| `WORKING MEMORY` | Execute scratchpad |
| `PRIOR CONVERSATION` | Chat replay; assess uses execute ledger |

Enforcement: dedicated `build_plan_assess_message_v2()` that **does not call** `_append_plan_context_sections()` — only the allowlist builder above. Prevents future bundle fields from leaking in.

### PRIOR PROGRESS refinement

Keep RFC-227 digest but **de-noise for assess**:

| Field | Current | Target |
|-------|---------|--------|
| `derived_progress_hint` | Shown verbatim | Rename label to `wave_hint (non-binding)` or **omit hint** when Phase E gap present |
| `tool_calls` | Up to 8 | **Omit** — already in step summaries / execute AI |
| `step_summaries` | Up to 8 | Keep, cap **4** most recent |
| `evidence_excerpts` | Up to 3 | Keep |
| Header `progress_hint=` | Can read “high” from digits | Add footer: `hint is heuristic only — judge GOAL components` |

Stale rule unchanged: omit when `prior_progress.iteration < current_iteration - 1`.

### Optional gap feed-forward (Phase E)

When `plan_gap_analysis` runs, **replace** redundant context:

- No Slice A
- No `PRIOR GOALS` / `GOAL LINEAGE`
- `PRIOR PROGRESS` shortened to header + step tree only (no hint)
- Gap block is the authoritative “what’s left” narrative

### Mode matrix

| Mode | Ledger | Envelope sections |
|------|--------|-------------------|
| **new_goal, no execution** | Empty | `GOAL` + `TASK` only |
| **new_goal, in-flight execute** | execute AI only | `GOAL` + `PRIOR PROGRESS` + `TASK` |
| **mid_goal** | execute AI only (current segment) | Full allowlist minus gap if E disabled |
| **mid_goal + Phase E** | execute AI only | `GOAL` + `GAP ANALYSIS` + `PRIOR PROGRESS` + `PLAN COVERAGE` + `PREVIOUS ASSESSMENT?` + `TASK` |

**Continuation discriminator** (`call_kind=continuation`) is **out of scope** for this envelope — it keeps `project_continuation_assess_ledger` until a separate IG.

### Before / after (mid-goal complex continuation)

**Before** (~8–40 ledger turns + 6 envelope sections potential):

```
System + PLAN_ASSESS
[goal_completion H/A with completion report]      ← noise
[intent_classify H/A JSON]                        ← noise
[plan_generate H/A with steps + reasoning]          ← noise
[execute H/A × N]
[execute human × N — large instructions]          ← noise
GOAL + PRIOR PROGRESS + SKILL? + PRIOR GOALS? + …
TASK
```

**After** (~4–12 ledger turns + 4–6 envelope sections):

```
System + PLAN_ASSESS (+ language hint only)
[execute AI × N — compacted outcomes]
GOAL (full)
GAP ANALYSIS (components + distance)              ← Phase E
PRIOR PROGRESS (step tree + excerpts, no hint)    
PREVIOUS ASSESSMENT (one line)                    
PLAN COVERAGE (deterministic 2/5 remaining)       
TASK
```

Expected token reduction: **30–50%** input on mid-goal assess; larger on continuation goals where Slice A was heavy.

### Config knobs

```yaml
agent:
  loop:
    plan_assess_prompt:
      enabled: true                    # master switch for v2 assess assembly
      ledger_max_messages: 24            # assess-specific tail (not shared 40)
      execute_ai_max_chars: 400          # per execute AI row in projection
      keep_head_tail_execute_ai: true    # preserve first wave + recent when truncating
      omit_prior_progress_hint: true     # drop derived_progress_hint label
      include_plan_coverage: true        # deterministic remaining-steps block
      include_skill_reference: false     # hard off (denylist)
```

### Implementation mapping

| Architecture piece | Phase | Primary file |
|---------------------|-------|--------------|
| Assess ledger filter (AI-only, no Slice A) | A | `plan_ledger_projection.py` |
| Envelope allowlist / denylist builder | A | `user_message.py` |
| System tier suppress bundle memory | A | `builder.py` |
| `PLAN COVERAGE` deterministic block | A | `plan_step_safety.py` or `user_message.py` |
| PRIOR PROGRESS de-noise | A | `user_message.py` |
| Execute AI compaction at projection | A | `plan_ledger_projection.py` |
| `PREVIOUS ASSESSMENT` inline | C | `user_message.py` |
| `GAP ANALYSIS` inline | E | `user_message.py` |
| Guardrails respect gap + plan coverage | B, E | `plan_assess.py`, `plan_step_safety.py` |

### Success criteria (prompt quality)

| Signal | Target |
|--------|--------|
| Zero `goal_completion` phase rows in assess prompt | 100% |
| Zero `plan_generate` / `intent_classify` rows in assess prompt | 100% |
| Exactly one `GOAL:` block in assess prompt | 100% |
| Denylist sections absent even with `ContextBundle` passed | 100% |
| Assess `complete` rate on multi-part complex goals without full evidence | Near-zero |

---

## Target Design (implementation phases)

Implementation of the prompt architecture above.

### 1. Assess-specific projection (P0)

Replace shared mid-goal planner projection for assess with `project_planner_ledger_for_assess`:

```python
def project_planner_ledger_for_assess(
    loop_messages: list[BaseMessage],
    state: LoopState,
    ledger_cfg: PlanPromptLedgerConfig | None,
) -> list[BaseMessage]:
    """Assess-only ledger: current-goal execute_step AI rows, compacted."""
    seg_start = _current_goal_segment_start(loop_messages)
    segment = [
        _compact_execute_ai_for_assess(_deep_copy_message(m))
        for m in loop_messages[seg_start:]
        if getattr(m, "phase", None) == "execute_step" and _is_loop_ai_message(m)
    ]
    # head+tail when over cap; never inject Slice A or plan phases
    return project_loop_messages_for_plan(segment, ledger_cfg)
```

Wire via `project_planner_ledger(..., call_kind="assess")` → delegates to function above.

**Rationale**: Mid-goal assess judges **current goal execution evidence** only. Prior goal completion, intake, and plan drafts are excluded per § High-Accuracy Prompt Architecture.

**Preserve Slice A for**:

- `call_kind=generate` (decomposition may need prior recommendations)
- `call_kind=continuation` (unchanged — uses `project_continuation_assess_ledger`)
- Execute-step Slice A (IG-542 — executor needs prior grounding)

### 2. Mid-goal execution-evidence guard (P0)

Extend `node_plan_assess` before `goal_progress == "complete"` routing:

```python
def assess_may_route_complete(
    state: LoopState,
    assessment: StatusAssessment,
    intake_label: IntakeLabel | None,
) -> bool:
    """Return False when 'complete' would be premature for the current goal."""
    if assessment.goal_progress != "complete":
        return True

    # Complex goals need current-goal execution evidence at any iteration
    if intake_label == IntakeLabel.COMPLEX:
        if not state.step_results and not _current_goal_has_execute_ledger(state):
            return False
        if state.has_remaining_steps():
            return False

    return True
```

On rejection: downgrade `goal_progress` to `medium` or `high`, set `assess_route=continue_generate`.

**Scope**: All iterations (not just iter=0). Complements IG-555 without replacing it.

### 3. Inline last-assessment envelope (P1)

Inject compact continuity from `state.previous_plan` into assess human text:

```
PREVIOUS ASSESSMENT (continuity):
- Status: continue, Progress: medium
- Reasoning: I checked X; more work needed on Y.
```

Wire in `UserMessageBuilder.build_plan_assess_message` (partially exists in `_build_human_message` for non-plan paths; not currently on assess envelope).

**Rationale**: Restores assess continuity without re-injecting full prior assess ledger pairs (which would bloat prompts and create self-anchoring).

### 4. Prior-progress hint override (P2, optional)

When `prior_progress.derived_progress_hint` and LLM `goal_progress` differ by >1 bucket **and** LLM says `complete`:

```python
if hint_idx <= medium and llm_idx >= complete_idx:
    assessment.goal_progress = "high"  # or force continue_generate
```

Log override for observability. Start as shadow mode (log only) before enabling.

### 5. Assess phase filter tightening (P2, optional)

Mid-goal current segment for assess: `execute_step` + **last** `plan_generate` pair only (drop older plan_generate history).

Reduces plan-decomposition anchoring; assess should judge evidence, not re-read every plan draft.

---

## Analysis: Plan-Gap-Analysis Before Plan-Assess

### Motivation

Plan-assess today conflates three cognitive tasks in **one** structured LLM call (`StatusAssessment`):

| Task | What assess must infer | Failure when conflated |
|------|------------------------|-------------------------|
| **Evidence inventory** | What did the last wave(s) actually prove? | Restates user goal instead of citing ledger (RFC-227 §3.1) |
| **Goal coverage map** | Which parts of GOAL are satisfied vs open? | Multi-part goals marked `complete` after one sub-task succeeds |
| **Routing decision** | continue / replan / done + progress bucket | Prior goal completion tone overrides thin current evidence |

A dedicated **plan-gap-analysis** phase separates tasks 1–2 from task 3. Assess then **routes** using an explicit gap report instead of re-deriving coverage from raw ledger + prior completion tone.

### What already exists (overlap)

| Mechanism | Provides | Does **not** provide |
|-----------|----------|---------------------|
| **`PriorProgressDigest`** (RFC-227) | Wave-level tool heads, excerpts, step summaries, `derived_progress_hint` | Goal-component coverage, remaining gaps, semantic distance from full GOAL |
| **`StatusAssessment`** | Routing (`status`, `goal_progress`) | Structured decomposition; evidence-to-component mapping |
| **`plan_assess_instructions.xml`** | Multi-part guard prose | Executable checklist the model must fill before routing |
| **`goal_description`** (intake Pass 2) | Normalized imperative summary | Per-component satisfaction status |
| **DAG / step anchor registry** | Plan-step structural state (completed/pending) | Whether plan steps cover GOAL scope (plan may be undersized) |
| **`state.has_remaining_steps()`** | Plan graph has pending steps | Whether GOAL scope is satisfied (plan may be wrong) |
| **IG-555 boundary marker** | De-bias prior completion tone | Current-goal evidence ↔ goal distance |

**Conclusion**: RFC-227 solved *evidence starvation*; IG-557 Phase A–D reduce *projection bias* and add *structural guards*. None produce an explicit **goal coverage map** that assess must respect. Gap analysis fills that hole.

### Feasibility: yes, with constraints

Adding plan-gap-analysis before plan-assess is **feasible and recommended for mid-goal paths** when implemented as:

- A **skippable** graph node (or conditional branch) — not on iter=0 first assess with empty ledger
- A **narrow structured schema** (~150–300 tokens output) — not a second full planner call
- **Assess-only projection** (Phase A) — no Slice A prior `goal_completion`
- **Inline feed-forward** — gap result injected into assess task envelope; assess prompt instructs routing to respect gap

**Not recommended** as a replacement for Phase A/B guardrails — gap analysis is probabilistic; structural guards remain the fail-safe.

### Architecture options compared

| Option | Graph change | LLM calls | Skip control | Observability | Verdict |
|--------|--------------|-----------|--------------|---------------|---------|
| **E1: New node `plan_gap_analysis`** | Yes — insert between `bounded_evidence_gather` and `plan_assess` | +1 when mid_goal | Clean conditional edge | Own Langfuse phase, TUI status | **Recommended** |
| **E2: Two-call inside `node_plan_assess`** | No | +1 when mid_goal | Branch inside node | Single node, two sub-phases | Acceptable fallback |
| **E3: Extend `bounded_evidence_gather`** | No (reuse node) | +1 | Mixed with IG-476 fresh-loop logic | Node name misleading | Avoid |
| **E4: Deterministic digest only** | No | 0 | N/A | Code-only | Insufficient for semantic multi-part goals |
| **E5: Prompt-only assess expansion** | No | 0 | N/A | None | Does not fix conflation |

**Recommendation**: **E1** — new node preserves RFC-220 phase clarity, matches `bounded_evidence_gather` → `plan_assess` spine, and allows skip without touching assess routing.

### Proposed graph topology (Phase E)

```
bounded_evidence_gather
    ├─ fresh-loop skip (IG-476) ──────────────────────→ plan_generate
    ├─ gap_skip (iter=0, no step_results, no execute ledger) ─→ plan_assess
    └─ default ───────────────────────────────────────→ plan_gap_analysis → plan_assess
```

Clarification resume adds origin `plan_gap_analysis` alongside existing plan-phase origins.

**Skip gap analysis when**:

- `iteration == 0` and no `step_results` and no current-goal `execute_step` ledger (first assess — nothing to gap)
- Fresh-loop bypass already routing to `plan_generate`
- Optional config: `agent.loop.plan_gap_analysis_enabled: false`
- Optional: skip for `trivial` intake (single-shot goals)

**Run gap analysis when**:

- `resolve_planner_projection_mode(state) == "mid_goal"`
- Or complex intake at iter=0 **after** first execute wave (`step_results` or execute ledger present — forced mid_goal)

### Proposed schema: `PlanGapAnalysis`

Lightweight structured output distinct from `StatusAssessment` — **no routing fields**.

```python
class GoalComponentStatus(BaseModel):
    """One decomposed facet of the current GOAL and its evidence state."""

    component: str = Field(max_length=120)  # e.g. "build docker image", "run e2e tests"
    status: Literal["not_started", "partial", "satisfied", "blocked"]
    evidence: str = Field(default="", max_length=200)  # cite step_id, tool, or excerpt
    gap: str = Field(default="", max_length=200)  # what is still missing for this component


class PlanGapAnalysis(BaseModel):
    """Explicit evidence inventory + distance from GOAL (feeds plan-assess, IG-557)."""

    components: list[GoalComponentStatus] = Field(min_length=1, max_length=8)
    evidence_summary: str = Field(max_length=400)  # neutral inventory of proven facts
    remaining_gaps: list[str] = Field(max_length=6)  # each ≤120 chars
    distance_from_goal: Literal["far", "moderate", "near", "at_goal"]
    gap_reasoning: str = Field(max_length=300)  # first-person, no routing jargon
```

**Decomposition inputs** (prompt context, not schema output):

- `GOAL:` / `intent.goal_description`
- `PRIOR PROGRESS:` digest (RFC-227)
- Current-goal `execute_step` ledger segment (assess-only projection)
- Optional: last `plan_generate` steps as *hypothesis* ("plan claimed these steps; verify against evidence")

**Explicit non-goals for gap schema**:

- No `status` (continue/replan/done) — reserved for assess
- No `goal_progress` bucket — assess maps from `distance_from_goal` + guards
- No prior goal completion in projection

### Prompt and projection for gap analysis

Reuse unified planner assembly (IG-538) with new `call_kind="gap"`:

```
1. SystemMessage  — plan_gap_analysis_instructions.xml (new fragment)
2. Projected ledger — same as assess mid_goal: execute_step + last plan_generate; NO Slice A
3. Task envelope  — GOAL / PRIOR PROGRESS / GAP TASK
```

**GAP TASK** (example):

```
Decompose GOAL into explicit components (2–8). For each component, classify evidence from
the ledger and PRIOR PROGRESS. List remaining_gaps and distance_from_goal.
Do NOT decide continue/replan/done — assessment follows separately.
```

**Ledger phase**: record human/AI pair with `phase=plan_gap_analysis`, `iteration=state.iteration`. Exclude from assess projection (same as `plan_assess` pairs) — assess receives gap via inline envelope only.

### Feed-forward into plan-assess

After gap analysis, stash on scratch and inject into assess human message:

```
GAP ANALYSIS (feeds assessment — do not contradict without citing new ledger evidence):
- distance_from_goal: moderate
- evidence_summary: Built image soothe:local; docker-compose not started.
- components:
  - [partial] build docker image — evidence: step 01 run_command build succeeded
  - [not_started] start components — gap: no compose up or health check in ledger
  - [not_started] run e2e tests — gap: no test runner invoked
- remaining_gaps: start stack, run e2e suite
```

Assess instructions addition:

- If any component is `not_started` or `partial` and GOAL requires it → `goal_progress` MUST NOT be `complete`
- If `distance_from_goal` is `far` or `moderate` → `status` MUST NOT be `done`
- Cite GAP ANALYSIS components in `assessment_reasoning` sentence 1

**Structural guard enhancement (Phase B + E)**:

```python
def assess_respects_gap_analysis(
    assessment: StatusAssessment,
    gap: PlanGapAnalysis | None,
) -> bool:
    if gap is None:
        return True
    if gap.distance_from_goal in ("far", "moderate"):
        if assessment.goal_progress == "complete" or assessment.status == "done":
            return False
    open_components = [
        c for c in gap.components if c.status in ("not_started", "partial", "blocked")
    ]
    if open_components and assessment.goal_progress == "complete":
        return False
    return True
```

On violation: downgrade assessment and route `continue_generate` (same as Phase B).

### Latency and cost

| Path | Extra LLM call | Typical tokens | When |
|------|--------------|----------------|------|
| First assess (iter=0, no execution) | 0 (skipped) | — | Unchanged |
| Mid-goal assess | +1 gap call | ~800–1500 input, ~200–350 output | Every post-wave cycle |
| Simple single-wave goal | 0 (optional skip) | — | Configurable |

Mitigations:

- Route gap call through `plan_assess_model_role` or a dedicated `plan_gap_model_role: fast` config knob
- Skip for `simple` intake when `derived_progress_hint=high` and single-step plan complete (shadow first)
- Run gap + assess as **serial** in one node (E2) only if graph change is blocked — same cost, worse observability

Expected accuracy gain: reduces premature `complete` on multi-part goals where one wave succeeded; gap forces explicit enumeration before routing.

### Relationship to Phase A–D

| Phase | Role | Gap analysis interaction |
|-------|------|--------------------------|
| **A** Assess projection | Remove Slice A bias | Gap uses **same** assess-only projection |
| **B** Execution guard | Structural fail-safe | Guard extended to check `PlanGapAnalysis` |
| **C** Previous assessment | Assess continuity | Orthogonal — assess sees prior routing + gap |
| **D** Hint override | Telemetry → override | Gap `distance_from_goal` can supersede hint disagreement |
| **E** Gap analysis | Explicit coverage map | **Primary accuracy lever for mid-goal** |

Phase E is **additive** to A–B; implement A–B first (no extra latency), then E for complex/mid-goal paths.

---

## Implementation Phases

### Phase A — Assess prompt noise optimization + projection (P0)

| File | Change |
|------|--------|
| `prompts/plan_ledger_projection.py` | `project_planner_ledger_for_assess`, `_compact_execute_ai_for_assess`, head+tail truncate |
| `prompts/user_message.py` | `build_plan_assess_message_v2()` with allowlist/denylist; `PLAN COVERAGE` block; PRIOR PROGRESS de-noise |
| `prompts/builder.py` | Assess path: v2 envelope, suppress bundle memory in system, `call_kind=assess` projection |
| `config/models.py` + template/develop yml | `PlanAssessPromptConfig` knobs |
| `tests/unit/core/prompts/test_planner_ledger_projection_modes.py` | Assert zero goal_completion/plan_generate/intent in assess projection |
| `tests/unit/core/prompts/test_plan_assess_prompt_v2_ig557.py` | Denylist sections absent even with ContextBundle; single GOAL |
| `tests/unit/core/prompts/test_plan_ledger_projection_ig380.py` | Generate mid_goal unchanged |

**Acceptance**:

- Assess prompt contains **zero** rows with phase ∈ `{goal_completion, intent_classify, plan_generate, plan_assess}`
- Assess prompt contains **zero** `execute_step` Human rows
- Exactly **one** `GOAL:` in task envelope; full goal text at new_goal (no 120-char preview)
- `PRIOR GOALS`, `GOAL LINEAGE`, `STEP LINEAGE`, `DAG STATUS`, `SKILL REFERENCE` absent even when `ContextBundle` populated
- `PLAN COVERAGE` present when `state.current_decision` has steps
- Generate projection unchanged (still includes Slice A + plan_generate)

### Phase B — Mid-goal execution-evidence guard (P0)

| File | Change |
|------|--------|
| `cognition/plan_step_safety.py` | Add `assess_may_route_complete(state, assessment, intake_label)` |
| `orchestrator/nodes/plan_assess.py` | Call guard before `goal_progress == "complete"` routing; merge with IG-555 iter=0 logic |
| `tests/unit/core/loop/orchestrator/nodes/test_plan_assess_ig557_guardrail.py` | Mid-goal premature complete rejection |

**Acceptance**:

- Complex intake, iteration=1, no step_results, assess returns `complete` → `assess_route=continue_generate`
- Complex intake, iteration=1, step_results present, remaining plan steps → reject `complete`
- Simple intake, iteration=1, assess returns `complete` with evidence → routes to goal_done (no false rejection)

### Phase C — Inline last-assessment envelope (P1)

| File | Change |
|------|--------|
| `prompts/user_message.py` | Add `PREVIOUS ASSESSMENT` section to `build_plan_assess_message` when `state.previous_plan` present |
| `prompts/builder.py` | Pass `state.previous_plan` into assess message builder |
| `tests/unit/core/prompts/test_builder_plan_assess_continuity.py` | Assert section present/absent correctly |

### Phase D — Hint override + phase filter (P2, optional)

| File | Change |
|------|--------|
| `cognition/planner.py` | Optional hint override after assess LLM call |
| `prompts/plan_ledger_projection.py` | Optional assess-only phase filter for plan_generate history |
| Config | `agent.loop.plan_assess_hint_override: bool` (default false, shadow first) |

### Phase E — Plan-gap-analysis node (P1, recommended for mid-goal)

| File | Change |
|------|--------|
| `state/schemas.py` | Add `PlanGapAnalysis`, `GoalComponentStatus`; `LoopState.plan_gap: PlanGapAnalysis \| None` |
| `orchestrator/nodes/plan_gap_analysis.py` | New node: build gap messages, invoke structured LLM, record ledger, set scratch |
| `orchestrator/builder.py` | Insert node; conditional edges from `bounded_evidence_gather` and to `plan_assess` |
| `orchestrator/routing.py` | Add `route_after_evidence_gather` gap branch; `route_after_gap`; clarification origin |
| `orchestrator/phase_scratch.py` | `plan_gap: PlanGapAnalysis \| None` |
| `orchestrator/state.py` | `GapAnalysisRoute`, graph state keys |
| `cognition/planner.py` | `analyze_plan_gap()` method; ledger recording |
| `cognition/phase.py` | Delegate to planner |
| `prompts/planner_assembly.py` | Extend `PlannerCallKind` with `"gap"` |
| `prompts/builder.py` | `build_plan_messages(..., call_kind="gap")`; assess-only projection |
| `prompts/user_message.py` | `build_plan_gap_message()` |
| `prompts/fragments/instructions/plan_gap_analysis_instructions.xml` | New assess-adjacent fragment |
| `prompts/fragments/instructions/plan_assess_instructions.xml` | Add GAP ANALYSIS respect rules |
| `prompts/plan_ledger_projection.py` | Exclude `plan_gap_analysis` phase from assess/generate projection |
| `config/models.py` + template/develop yml | `plan_gap_analysis_enabled`, optional `plan_gap_model_role` |
| `tests/unit/.../test_plan_gap_analysis*.py` | Schema, projection, skip routing, guard integration |
| `tests/integration/.../test_loop_agent_continuation_planning.py` | Multi-part goal does not early-complete |

**Acceptance**:

- iter=0, no execution → `bounded_evidence_gather → plan_assess` (gap skipped)
- iter=1, complex goal, partial wave → gap runs; assess human contains `GAP ANALYSIS` block
- Gap returns `distance_from_goal=moderate` with open components → assess `complete` rejected by guard
- Gap ledger recorded with `phase=plan_gap_analysis`; excluded from next assess projection
- Latency: +1 LLM call only on mid-goal paths

### Phase F — Gap-informed plan-generate (P2, optional)

When assess routes `continue_generate`, pass `PlanGapAnalysis.remaining_gaps` into plan-generate envelope as `OPEN GAPS:` section so replan targets uncovered components explicitly.

| File | Change |
|------|--------|
| `prompts/user_message.py` | `build_plan_generate_message(..., plan_gap=...)` |
| `orchestrator/nodes/plan_generate.py` | Forward scratch `plan_gap` to planner |

---

## Observability

| Event | Log prefix |
|-------|------------|
| Slice A omitted for assess | `[Plan] assess projection: Slice A omitted (mid_goal assess-only)` |
| Premature complete rejected | `[Plan] Reject goal_progress=complete: insufficient execution evidence (iter=N)` |
| Gap analysis skipped | `[Plan] gap analysis skipped (reason=iter0_no_execution)` |
| Gap analysis completed | `[Plan] gap distance=%s open_components=%d` |
| Assess rejected vs gap | `[Plan] Reject assessment: contradicts gap analysis (distance=%s)` |
| Hint override (shadow) | `[Plan] prior_progress hint=%s vs LLM goal_progress=%s — would override` |
| Hint override (active) | `[Plan] prior_progress override: complete → high` |

Extend `_log_prior_progress_disagreement` metrics for tuning. Emit TUI `plan_phase_status` during gap call ("Analyzing goal coverage").

---

## Success Criteria

| Criterion | Target |
|-----------|--------|
| Mid-goal premature complete on complex multi-wave goals | Near-zero (guard + gap + projection) |
| Assess projection excludes Slice A at mid_goal | 100% when `call_kind=assess` |
| Generate projection retains Slice A | No regression |
| Gap analysis skip on first assess | 100% when no execution evidence |
| Gap analysis run on mid-goal | 100% when mid_goal + enabled |
| Gap → assess feed-forward | Assess envelope includes GAP ANALYSIS on mid-goal |
| Assess respects gap (guard) | `complete` rejected when gap shows open components |
| Continuation reference resolution at generate/execute | Unchanged (Slice A preserved for non-assess paths) |
| Simple/trivial single-wave completion | Still routes to goal_done when evidence supports it |
| Latency | Phase A–D: no extra LLM calls; Phase E: +1 call mid-goal only (~2–4s) |

---

## Out of Scope

- Changing execute-step Slice A projection (IG-542)
- Intake Pass 2 prior projection (IG-554 / IG-540)
- Replacing `PRIOR PROGRESS` digest with gap analysis (digest remains; gap builds on it)
- Fine-tuning or model changes
- Wire protocol / TUI changes (except `plan_phase_status` label for gap)
- RFC-220 topology changes beyond inserting one skippable node (Phase E)

---

## Open Questions

1. **Continuation assess-only goals at iter=0 with step_results** — Should assess omit Slice A when `continue_loop` and `step_results` present (forced mid_goal)?
2. **Complex guard threshold** — Require ≥1 wave vs require all plan steps complete before `complete`?
3. **Separate `cross_goal_completion_tail` for assess** — Config knob vs hard-coded omission?
4. **Shadow period** — How many integration runs before enabling hint override?
5. **Gap decomposition source** — LLM-only vs seed components from `intent.goal_description` + delimiter heuristics (`then`, `and`, numbered lists)?
6. **Gap skip for simple intake** — Always run on mid_goal, or only `complex`?
7. **E1 vs E2** — Ship graph node first, or prototype as two-call inside `plan_assess` for faster validation?
8. **Phase F timing** — Feed gaps to plan-generate on every replan, or only when assess returns `replan`?

---

## Files (expected)

```
packages/soothe/src/soothe/foundation/sloop/prompts/plan_ledger_projection.py
packages/soothe/src/soothe/foundation/sloop/prompts/builder.py
packages/soothe/src/soothe/foundation/sloop/prompts/user_message.py
packages/soothe/src/soothe/foundation/sloop/prompts/planner_assembly.py
packages/soothe/src/soothe/foundation/sloop/prompts/fragments/instructions/plan_gap_analysis_instructions.xml
packages/soothe/src/soothe/foundation/sloop/prompts/fragments/instructions/plan_assess_instructions.xml
packages/soothe/src/soothe/foundation/sloop/cognition/plan_step_safety.py
packages/soothe/src/soothe/foundation/sloop/cognition/planner.py
packages/soothe/src/soothe/foundation/sloop/cognition/phase.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/plan_assess.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/plan_gap_analysis.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/bounded_evidence_gather.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/builder.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/routing.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/phase_scratch.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/state.py
packages/soothe/src/soothe/foundation/sloop/state/schemas.py
packages/soothe/src/soothe/config/models.py
config/config.template.yml
config/develop/config.yml
packages/soothe/tests/unit/core/prompts/test_planner_ledger_projection_modes.py
packages/soothe/tests/unit/core/prompts/test_plan_ledger_projection_ig380.py
packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_assess_ig557_guardrail.py
packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_gap_analysis_ig557.py
packages/soothe/tests/unit/core/prompts/test_builder_plan_assess_continuity.py
packages/soothe/tests/integration/core/test_loop_agent_continuation_planning.py
```

---

## Recommended implementation order

```
Phase A (prompt v2 + projection) ──┐
Phase B (guard)                    ──┼── P0: accuracy foundation
                                   │
Phase C (continuity)               ──┘
Phase E (gap analysis)             ─── P1: explicit coverage map
Phase D (hint override)            ── P2: optional tuning
Phase F (gap → generate)           ── P2: replan targeting
```

---

## References

- RFC-214: Loop Message Surface (ledger phases, projection)
- RFC-220: StrangeLoop graph topology
- RFC-227: Prior Progress Digest (wave evidence; gap builds on this)
- RFC-604: Reason-phase split (StatusAssessment schema)
- RFC-630: Start-Phase LLM Intake and Branch Routing
- IG-555: Plan-Assess Prior Goal Completion Bias Mitigation (iter=0)
- IG-538: Unified Planner Prompt Assembly
- IG-542: Execute-Step Ledger Projection (Slice A/B)
- IG-551: Mid-Loop Continuation Planning Coordination
- Draft: `docs/drafts/2026-07-07-plan-assess-prior-goal-bias-mitigation.md`
