# IG-557: Mid-Goal Plan-Assess Accuracy

**RFCs**: RFC-206 (prompt tiers), RFC-214 (ledger + planner assembly), RFC-220 (loop graph), RFC-225 (goal record / continuation), RFC-226 (continuation assess), RFC-227 (prior-progress digest), RFC-604 (`StatusAssessment`), RFC-624 (CE `GoalNode` / ledger), RFC-630 (intake routing)
**Created**: 2026-07-07
**Status**: Draft
**Related**: IG-555 (iter=0 prior-completion bias), IG-538 (unified planner assembly), IG-542 (execute Slice A), IG-551 (continuation coordination)
**Motivating observation**: After the first execution wave, plan-assess can return `goal_progress="complete"` and route to goal completion despite incomplete multi-part goals — especially on continuation goals where Slice A prior `goal_completion` tone dominates current-wave evidence.

---

## RFC Alignment

IG-557 implements mid-goal assess accuracy on the existing planner stack (RFC-214 §4 / IG-538). Where assess behavior diverges from RFC-214 defaults, this IG is the **amendment source** — update RFC-214 §3 and §4.3–§4.5 when IG-557 lands.

| RFC | Relationship | IG-557 change |
|-----|--------------|---------------|
| **RFC-214 §3, G7** | **Amends** | `plan_assess` H/A pairs are **not** appended to CE `LedgerManager`; audit on `GoalNode.last_assessment` (RFC-624) |
| **RFC-214 §4.3** | **Amends** (`call_kind=assess` only) | Strict phase allowlist: current-goal `execute_step` **AI only**; no Slice A, no `plan_generate` / `intent_classify` |
| **RFC-214 §4.4** | **Amends** (`call_kind=assess` only) | Task envelope allowlist/denylist; full `GOAL:` text (no description preview truncation); no `PRIOR GOALS` / lineage / `DAG STATUS` at mid_goal assess |
| **RFC-214 §4.5** | **Supersedes** mid_goal assess example | Assess stack excludes plan-phase ledger rows (by Phase G + assess projection) |
| **RFC-206** | Implements | Assess system tier: `plan_assess_instructions.xml` + language hint only |
| **RFC-220** | Amends (Phase E) | Optional skippable `plan_gap_analysis` node on complex spine |
| **RFC-225** | Unchanged | Continuation seeding, goal enrichment; assess reads CE, not duplicated `GoalExecutionRecord` fields |
| **RFC-226** | Unchanged | `call_kind=continuation` keeps `project_continuation_assess_ledger` and continuation envelope |
| **RFC-227** | Extends render | `<PRIOR_PROGRESS>` de-noised for assess; digest production unchanged; **RFC-227 §4 P4 preserved** (telemetry only, no code override of `StatusAssessment`) |
| **RFC-604** | Unchanged | `StatusAssessment` schema and assess instruction contract |
| **RFC-624** | Extends model | `GoalNode.last_assessment`, `last_assessment_iteration`; optional `last_gap_analysis` |
| **RFC-630** | Unchanged | Intake routing; complex spine unchanged except optional gap insert |

**Superseded patterns (do not implement):**

- RFC-214 §3 rationale item 1 (assess ledger rows for prompt-cache prefix) — replaced by CE `last_assessment` inline continuity (Phase C/G)
- RFC-214 §4.3 mid_goal “all phases included” for `call_kind=assess` — replaced by assess-only filter (Phase A)
- RFC-214 §4.4 mid_goal envelope blocks (`PRIOR GOALS`, `DAG STATUS`, etc.) for `call_kind=assess` — replaced by allowlist (Phase A)
- Pre-CE `GoalExecutionRecord.loop_messages` mirroring — RFC-624 CE ledger is sole write path (`ce.ledger.record_message`)

---

## Executive Summary

IG-555 mitigated prior-goal completion anchoring at **iter=0** (boundary marker + complex undersized-plan guardrail). The same failure mode persists at **mid-goal** (`iteration ≥ 1`, or iter=0 with `step_results`): under RFC-214 default mid_goal projection, assess sees prior goal completion in Slice A and non-evidence plan phases, while prior assess turns are excluded from projection — producing premature `goal_progress="complete"`.

**Solution** (phased, RFC-aligned):

1. **Phase A** — Assess-only ledger projection + task envelope per RFC-214 §4 amendment (execute AI only; denylist envelope sections)
2. **Phase G** — Amend RFC-214 §3: no `plan_assess` ledger pairs; audit on **`GoalNode.last_assessment`** (RFC-624)
3. **Phase B** — Structural guard before `goal_progress=complete` routing (all iterations)
4. **Phase C** — `PREVIOUS ASSESSMENT` inline from CE `last_assessment` (replaces ledger replay / cache-prefix rationale)
5. **Phase E** — Optional `plan_gap_analysis` node (RFC-220); CE `last_gap_analysis` audit, no ledger pair

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

## Normative Baseline and IG-557 Delta

### Assembly (RFC-214 §4, IG-538)

`PromptBuilder.build_plan_messages(..., plan_phase="assess")` → `assemble_planner_prompt(call_kind="assess", ...)`:

```
1. SystemMessage  — RFC-206 static tier (assess instructions; see Phase A system filter)
2. Projected ledger — CE `LedgerManager` messages, read-side caps (RFC-214 §4.3)
3. Task envelope — LoopHumanMessage (RFC-214 §4.4 plain-text sections + TASK)
```

Projection mode unchanged: `new_goal` if `iteration == 0 and not step_results`, else `mid_goal` (`resolve_planner_projection_mode`).

### RFC-214 default vs IG-557 assess contract

| Aspect | RFC-214 default (`call_kind=assess`) | IG-557 assess contract |
|--------|--------------------------------------|-------------------------|
| **Mid_goal ledger phases** | All phases (plan + execute) | `execute_step` **AI only**, current-goal segment |
| **Slice A** (`goal_completion`) | Included (IG-542 planner path) | **Excluded** |
| **Task envelope (mid_goal)** | `PRIOR PROGRESS`, `DAG STATUS`, optional bundle sections | Allowlist only (§ Assess Prompt Contract) |
| **Post-call persistence** | H/A pairs → CE ledger (`phase=plan_assess`) | **`GoalNode.last_assessment`** only (Phase G) |
| **Cross-wave assess continuity** | Prior assess in ledger (excluded from projection today) | **`PREVIOUS ASSESSMENT`** from CE (Phase C) |
| **Same-wave routing to generate** | `scratch.plan_assessment` → inline `ASSESSMENT:` | Unchanged |

**Unchanged paths:** `call_kind=generate` (RFC-214 mid_goal all phases + Slice A), `call_kind=continuation` (RFC-226), execute Slice A/B (IG-542 / RFC-214 §3.1).

### Post-call persistence (Phase G — RFC-214 §3 amendment)

| Store | Where | Purpose |
|-------|-------|---------|
| **`last_assessment`** | `GoalNode` (RFC-624) | Audit, debug, Phase C inline |
| **`scratch.plan_assessment`** | `LoopPhaseScratch` | Same-iteration routing → plan-generate `ASSESSMENT:` |
| **`assess` wire event** | TUI / observability | Existing assessment card |

**Remove:** `ce.ledger.record_message(..., phase="plan_assess")` from `LLMPlanner.assess_status()`.

Checkpoints may contain historical `plan_assess` ledger rows from pre-IG-557 runs; assess projection continues to exclude them. No backfill.

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
| **Assess amnesia (by design)** | Prior assess ledger pairs excluded from projection; continuity via CE **`last_assessment`** + inline `PREVIOUS ASSESSMENT` (Phase C/G) |
| **Guardrail gap** | IG-555 guards only `iteration == 0` + complex intake before `goal_progress=complete` routing |
| **Hint ignored** | RFC-227 §4 P4: telemetry-only disagreement logging; no code override of `StatusAssessment` |
| **Ledger tail loss** | Default 40-message cap may drop early-wave execute evidence on long goals |

### Why IG-555 is insufficient

| IG-555 intervention | Mid-goal gap |
|---------------------|--------------|
| Boundary marker on goal_completion human | AI completion body still carries "done" narrative |
| Undersized-plan guard at iter=0 | No guard when `iteration ≥ 1` |
| Complex intake replan at iter=0 | Mid-wave assess can still return `complete` after partial execution |

---

## Assess Prompt Contract (RFC-214 §4 amendment)

Design target: **one routing decision** (`StatusAssessment`, RFC-604) grounded on **current-goal evidence only**. Everything else is either excluded or reduced to a compact, non-directive summary. Applies only to `call_kind=assess`; generate and continuation paths remain RFC-214 / RFC-226 normative.

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
| P8 | **No assess ledger pairs** | Assess audit on CE `GoalNode.last_assessment` only; never replay assess H/A in prompts |

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
│   PREVIOUS ASSESSMENT (Phase C; when CE last_assessment present) │
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
<full goal text — RFC-214 §4.4 preview truncation waived for assess>

GAP ANALYSIS:          # Phase E; omitted when gap node skipped
<inline PlanGapAnalysis render>

PRIOR PROGRESS:        # mid_goal only; omitted at first assess
<refined digest — see below>

PREVIOUS ASSESSMENT:   # Phase C; from CE GoalNode.last_assessment (not ledger)
Status: continue | replan | done
Progress: none | low | medium | high | complete
Reasoning: <assessment_reasoning truncated ≤120 chars>

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
|-----|-------|--------------|
| Assess ledger filter (RFC-214 §4.3 amend) | A | `plan_ledger_projection.py` |
| Envelope allowlist / denylist builder | A | `user_message.py` |
| System tier suppress bundle memory | A | `builder.py` |
| `PLAN COVERAGE` deterministic block | A | `plan_step_safety.py` or `user_message.py` |
| PRIOR PROGRESS de-noise | A | `user_message.py` |
| Execute AI compaction at projection | A | `plan_ledger_projection.py` |
| `PREVIOUS ASSESSMENT` inline | C | `user_message.py` |
| `GAP ANALYSIS` inline | E | `user_message.py` |
| Guardrails respect gap + plan coverage | B, E | `plan_assess.py`, `plan_step_safety.py` |
| CE assess audit + no ledger pair | G | `context/models.py`, `context/engine.py`, `planner.py` |

### Success criteria (prompt quality)

| Signal | Target |
|--------|--------|
| Zero `goal_completion` phase rows in assess prompt | 100% |
| Zero `plan_generate` / `intent_classify` rows in assess prompt | 100% |
| Exactly one `GOAL:` block in assess prompt | 100% |
| Denylist sections absent even with `ContextBundle` passed | 100% |
| Assess `complete` rate on multi-part complex goals without full evidence | Near-zero |

---

## Implementation Design

### Phase A — Assess-specific projection

Wire `project_planner_ledger(..., call_kind="assess")` → `project_planner_ledger_for_assess` (see § Assess Prompt Contract). **Do not** change `call_kind=generate` or RFC-226 continuation projection.

### Phase B — Mid-goal execution-evidence guard

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

### Phase C — Inline last-assessment envelope

Inject compact continuity from **CE `GoalNode.last_assessment`** (prior assess on this goal):

```
PREVIOUS ASSESSMENT (continuity):
- Status: continue, Progress: medium
- Reasoning: I checked X; more work needed on Y.
```

Wire in `UserMessageBuilder.build_plan_assess_message_v2()` — read via CE goal node, not ledger replay. Replaces RFC-214 §3 assess ledger continuity rationale.

**Same-wave routing:** `scratch.plan_assessment` → plan-generate inline `ASSESSMENT:` (unchanged).

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

### Relationship to `bounded_evidence_gather`

Today there is **no functional overlap** — the nodes sit adjacent on the graph but do different jobs:

| | `bounded_evidence_gather` (today) | `plan_gap_analysis` (proposed) |
|--|-----------------------------------|--------------------------------|
| **Implementation** | Routing stub (IG-476 fresh-loop detect only) | Structured LLM read of existing ledger |
| **LLM** | No | Yes (~200–350 output tokens) |
| **Tools / CoreAgent** | No (placeholder for IG-394) | **No (by design — see below)** |
| **Output** | `evidence_gather_route` + optional synthetic `StatusAssessment` | `PlanGapAnalysis` on scratch |
| **When** | Every complex-spine iteration | Mid-goal only (after execute evidence exists) |

**Future IG-394** (`bounded_evidence_gather` as ledger-driven bounded tool rounds) is the **correct** place for pre-assess **evidence acquisition** when the ledger is empty at iter=0 complex intake. Gap analysis must **not** absorb that role.

**Sequential complement** (when IG-394 lands):

```
bounded_evidence_gather
  ├─ fresh-loop → plan_generate (IG-476, unchanged)
  ├─ thin ledger + complex → optional bounded tool rounds (IG-394) → re-enter gather or proceed
  └─ evidence present → plan_gap_analysis → plan_assess
```

Gap `remaining_gaps` may **inform** whether IG-394 rounds run in a later iteration, but gap itself never executes tools.

**Do not** implement option E3 (extend `bounded_evidence_gather` with gap LLM + tools) — mixes routing, acquisition, and interpretation in one misleading node.

### Non-goals: no tool execution in plan-gap-analysis

**Decision (locked):** `plan_gap_analysis` is **read-only**. It interprets evidence already recorded by execute; it does **not** run tools, invoke CoreAgent, or append new `execute_step` ledger rows.

#### Rationale

| Concern | Why tools belong elsewhere |
|---------|---------------------------|
| **Phase contract** | Gap = evidence ↔ GOAL mapping. Tool runs = fact acquisition → execute / IG-394. |
| **Ledger authority** | New facts must flow through execute (budgets, stamping, step cards, CE feedback, RFC-214 ledger rules). |
| **Assess grounding** | If gap ran tools mid-spine, assess would judge gap-produced evidence — circular and hard to debug. |
| **Latency envelope** | Gap targets one cheap structured call; tool rounds are unbounded. |
| **Failure semantics** | Tool failures need clarification, rate limits, `record_iteration` — execute pipeline only. |
| **IG-394 boundary** | Pre-assess tool rounds stay in `bounded_evidence_gather`; post-wave gap stays analytic. |

#### Allowed inputs (read-only)

- Compacted **execute_step AI** ledger (assess projection filter)
- **`PriorProgressDigest`** (RFC-227)
- Full **GOAL** + optional `intent.goal_description`
- **`PLAN COVERAGE`** (deterministic code block from `current_decision` / CE step state)
- Optional **component seeds** from code (delimiter parse of `goal_description`) — not tool calls

#### Explicitly forbidden in `node_plan_gap_analysis`

- `CoreAgent` / executor invocation
- `@tool` / MCP / shell / file reads
- Writing `execute_step` ledger pairs
- Mutating `state.step_results` or CE step execution records
- Side-effecting CE or workspace operations

#### Thin-ledger behavior (no tool fallback)

| Situation | Gap behavior | Tools? |
|-----------|--------------|--------|
| First assess, no execution | **Skip** gap node | No |
| Mid-goal, empty execute ledger | **Skip** gap; assess/replan decides | No |
| Mid-goal, partial evidence | Run gap on available evidence; open components → assess → `replan` → **execute** gathers more | No (execute next wave) |
| iter=0 complex, empty ledger, need context before first plan | Skip gap | **IG-394 only** (future), in `bounded_evidence_gather` |

When gap reports `distance_from_goal: far` with large `remaining_gaps`, the pipeline response is **assess → replan → execute**, not gap self-healing via tools.

#### Allowed deterministic enrichment (not tools)

Code may compute and inject without LLM tool use:

- `PLAN COVERAGE` (completed / remaining step ids)
- CE step status summaries already on `ContextBundle` (read-only projection)
- `state.has_remaining_steps()` / dependency closure

These are **inputs** to the gap prompt, not actions taken by the gap node.

#### Phase separation (locked)

| Phase | Responsibility | Tools? |
|-------|----------------|--------|
| **execute** | Acquire facts | ✅ Yes (primary) |
| **bounded_evidence_gather** | Route (IG-476); optional acquire when ledger thin (IG-394) | Future: bounded yes |
| **plan_gap_analysis** | Interpret evidence vs GOAL | ❌ **Never** |
| **plan_assess** | Route (`StatusAssessment`) | ❌ Never |
| **plan_generate** | Plan steps (LLM only) | ❌ Never |

#### Fragment contract (`plan_gap_analysis_instructions.xml`)

Must include:

```xml
<CONSTRAINT>
You MUST NOT request, simulate, or perform tool calls. Analyze ONLY the ledger
and PRIOR PROGRESS provided. If evidence is insufficient, list remaining_gaps
and set distance_from_goal accordingly — do not attempt to gather more data.
</CONSTRAINT>
```

#### Verification

- Unit: `node_plan_gap_analysis` does not import or call executor / CoreAgent
- Integration: mid-goal gap run produces zero new `execute_step` ledger rows
- Lint/guard (optional): assert `call_kind="gap"` planner path has empty tools list if shared invoke helper exists

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
    gap_reasoning: str = Field(max_length=2048)  # first-person, no routing jargon
```

**Decomposition inputs** (prompt context, not schema output):

- `GOAL:` / `intent.goal_description`
- `PRIOR PROGRESS:` digest (RFC-227)
- Current-goal `execute_step` **AI** ledger segment (assess-only projection)
- `PLAN COVERAGE:` deterministic block (plan step ids — not full plan_generate JSON)

**Explicit non-goals for gap schema and node**:

- No `status` (continue/replan/done) — reserved for assess
- No `goal_progress` bucket — assess maps from `distance_from_goal` + guards
- No prior goal completion in projection
- **No tool execution, CoreAgent invoke, or new execute ledger rows** (see § Non-goals: no tool execution)

### Prompt and projection for gap analysis

Reuse unified planner assembly (IG-538) with new `call_kind="gap"`:

```
1. SystemMessage  — plan_gap_analysis_instructions.xml (new fragment; includes no-tools CONSTRAINT)
2. Projected ledger — same as assess: current-goal execute_step AI only; NO Slice A, NO plan_generate
3. Task envelope  — GOAL / PRIOR PROGRESS / PLAN COVERAGE / GAP TASK
```

**GAP TASK** (example):

```
Decompose GOAL into explicit components (2–8). For each component, classify evidence from
the ledger and PRIOR PROGRESS. List remaining_gaps and distance_from_goal.
Do NOT decide continue/replan/done — assessment follows separately.
```

**Ledger phase**: assess and gap results are **not** recorded in `loop_messages`. Audit on CE goal node; assess receives gap via inline envelope only.

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

### Relationship to Phases A–C, E

| Phase | Role | Gap analysis interaction |
|-------|------|--------------------------|
| **A** Assess projection | RFC-214 §4.3 amend — remove Slice A / plan phases | Gap uses **same** assess-only projection |
| **B** Execution guard | Structural fail-safe | Guard extended to check `PlanGapAnalysis` |
| **C** Previous assessment | CE `last_assessment` inline | Orthogonal — prior routing + gap |
| **G** No assess ledger | RFC-214 §3 amend | Gap also CE-only audit (`last_gap_analysis`) |
| **E** Gap analysis | Explicit coverage map | **Primary accuracy lever for mid-goal** |

Phase E is **additive** to A + G + B; implement A + G + B first (no extra latency), then C and E.

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
- Exactly **one** `GOAL:` in task envelope; full goal text (RFC-214 §4.4 preview waived for assess)
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
| `prompts/user_message.py` | `PREVIOUS ASSESSMENT` section in `build_plan_assess_message_v2()` from CE `last_assessment` |
| `prompts/builder.py` | Pass `last_assessment` (from CE goal or scratch) into assess message builder |
| `tests/unit/core/prompts/test_builder_plan_assess_continuity.py` | Assert section from CE `last_assessment`; absent when None |

**Depends on:** Phase G (`last_assessment` populated before second assess on same goal).

### Phase G — Remove plan-assess ledger pairs; CE audit (P0)

**Decision (locked):** Stop appending `plan_assess` Human/AI pairs to CE `LedgerManager`. Persist **`StatusAssessment`** on the active **`GoalNode`** (RFC-624) for audit and Phase C continuity.

#### Schema (`GoalNode`)

```python
# context/models.py — GoalNode
last_assessment: dict[str, Any] | None = None
"""Serialized StatusAssessment from the most recent plan-assess on this goal."""

last_assessment_iteration: int | None = None
"""Loop iteration when last_assessment was written (debug/audit)."""
```

Store full `StatusAssessment.model_dump(mode="json")` including `assessment_reasoning` for audit. **Do not** project this into assess prompts except via truncated `PREVIOUS ASSESSMENT` inline block (Phase C).

Optional mirror on `LoopState` for same-turn reads is **not** required — use `scratch.plan_assessment` for in-flight routing.

#### ContextEngine API

```python
def set_last_assessment(
    self,
    goal_id: str,
    assessment: StatusAssessment,
    *,
    iteration: int,
) -> None:
    """Overwrite per-goal assess audit snapshot (RFC-624, IG-557)."""
    goal = self._dag.get_goal(goal_id)
    if goal is not None:
        goal.last_assessment = assessment.model_dump(mode="json")
        goal.last_assessment_iteration = iteration
```

Call from `LLMPlanner.assess_status()` **instead of** `ce.ledger.record_message(..., phase="plan_assess")`.

#### Remove from planner

```python
# DELETE in assess_status() after LLM call:
ce.ledger.record_message(recorded_human, phase="plan_assess")
ce.ledger.record_message(ai_msg, phase="plan_assess")
```

Compaction helpers (`compact_planning_human_content`, `compact_plan_assess_ai_dump`) are **not required** when ledger recording is removed.

#### Fix goal-boundary marker (same phase)

Replace `_goal_segment_start()` dependency on iter=0 `plan_assess` ledger rows (RFC-214 G7 pre-amendment artifact). Use `_current_goal_segment_start()` (after last `goal_completion` AI) or first `intent_classify` in segment.

#### Gap analysis (Phase E alignment)

Apply the same policy to `plan_gap_analysis`:

| | plan_assess | plan_gap_analysis |
|--|-------------|-------------------|
| Ledger H/A pair | **No** | **No** |
| CE audit field | `last_assessment` | `last_gap_analysis` (optional dict) |
| Prompt feed-forward | `PREVIOUS ASSESSMENT` | `GAP ANALYSIS` inline |

#### Persistence

`last_assessment` serializes with CE goal node (SQLite backend). Survives checkpoint/resume within the goal. Cleared or preserved on goal completion per existing goal lifecycle (preserve for completed goal audit).

| File | Change |
|------|--------|
| `context/models.py` | Add `last_assessment`, `last_assessment_iteration` on `GoalNode`; optional `last_gap_analysis` |
| `context/engine.py` | `set_last_assessment()`; optional `set_last_gap_analysis()` |
| `cognition/planner.py` | Remove assess ledger recording; call `set_last_assessment` |
| `prompts/plan_ledger_projection.py` | Fix `_goal_segment_start`; delete dead `current_iteration_plan_assess_in_ledger` if unused |
| `tests/unit/context/test_goal_last_assessment_ig557.py` | CE round-trip, overwrite semantics |
| `tests/unit/core/loop/planning/test_planner_ledger_recording.py` | Assert **no** ledger append; assert CE updated |
| `tests/unit/core/loop/utils/test_ledger_ce_sole_source.py` | Update assess recording expectations |

**Acceptance**:

- After `assess_status()`, `len(ce.get_messages())` unchanged (no new ledger rows)
- `goal.last_assessment["status"]` matches returned `StatusAssessment`
- Second assess on same goal shows `PREVIOUS ASSESSMENT` from CE (Phase C)
- `scratch.plan_assessment` still feeds same-wave `plan_generate` inline `ASSESSMENT:`
- Cross-goal Slice A collection works in fixtures **without** `plan_assess` rows
- Resume/reload restores `last_assessment` on CE goal node

### Phase D — ~~Hint override + phase filter~~ (removed)

Superseded by Phase A assess-only projection (no `plan_generate` in assess ledger at all). Hint-vs-LLM disagreement remains **telemetry only** per RFC-227 §4 P4 — no code-side rewrite of `StatusAssessment`.

### Phase E — Plan-gap-analysis node (P1, recommended for mid-goal)

| File | Change |
|------|--------|
| `state/schemas.py` | Add `PlanGapAnalysis`, `GoalComponentStatus`; `LoopState.plan_gap: PlanGapAnalysis \| None` |
| `orchestrator/nodes/plan_gap_analysis.py` | New node: build gap messages, invoke structured LLM, set scratch + CE audit (no ledger) |
| `orchestrator/builder.py` | Insert node; conditional edges from `bounded_evidence_gather` and to `plan_assess` |
| `orchestrator/routing.py` | Add `route_after_evidence_gather` gap branch; `route_after_gap`; clarification origin |
| `orchestrator/phase_scratch.py` | `plan_gap: PlanGapAnalysis \| None` |
| `orchestrator/state.py` | `GapAnalysisRoute`, graph state keys |
| `cognition/planner.py` | `analyze_plan_gap()` method; CE `set_last_gap_analysis` (no ledger) |
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
- **No** `plan_gap_analysis` ledger rows; `goal.last_gap_analysis` set on CE when enabled
- Latency: +1 LLM call only on mid-goal paths
- **Gap node produces zero new `execute_step` rows and never invokes CoreAgent/executor**
- **`plan_gap_analysis_instructions.xml` contains no-tools CONSTRAINT**

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
| CE last_assessment written | `[Plan] CE last_assessment iter=%d status=%s progress=%s` |
| Prior-progress disagreement (RFC-227 telemetry) | `[Plan] prior_progress hint=%s vs LLM goal_progress=%s` |

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
| **No plan_assess ledger rows** | `assess_status()` never appends to `loop_messages` |
| **CE last_assessment audit** | Every assess overwrites goal snapshot; survives CE persist |
| Latency | Phase A/B/G: no extra LLM calls; Phase E: +1 call mid-goal only (~2–4s) |

---

## Out of Scope

- Changing execute-step Slice A projection (IG-542)
- Intake Pass 2 prior projection (IG-554 / IG-540)
- Replacing `PRIOR PROGRESS` digest with gap analysis (digest remains; gap builds on it)
- **Tool execution inside `plan_gap_analysis`** (locked non-goal; IG-394 owns pre-assess gather)
- **Re-injecting plan-assess / plan_gap ledger into prompts** (continuity via CE + inline blocks only)
- Fine-tuning or model changes
- Wire protocol / TUI changes (except `plan_phase_status` label for gap)
- RFC-220 topology changes beyond inserting one skippable node (Phase E)
- **Code-side `derived_progress_hint` override** (conflicts with RFC-227 §4 P4)
- **Partial assess ledger retention** (e.g. last `plan_generate` pair only — superseded by Phase A execute-AI-only filter)

---

## Open Questions

1. **Continuation assess-only goals at iter=0 with step_results** — Should assess omit Slice A when `continue_loop` and `step_results` present (forced mid_goal)?
2. **Complex guard threshold** — Require ≥1 wave vs require all plan steps complete before `complete`?
3. **Separate `cross_goal_completion_tail` for assess** — N/A under Phase A (Slice A hard-off for assess); generate path keeps RFC-214 / IG-555 config.
4. ~~**Shadow period for hint override**~~ — **Removed** (RFC-227 telemetry-only).
5. **Gap decomposition source** — LLM-only vs seed components from `intent.goal_description` + delimiter heuristics (`then`, `and`, numbered lists)?
6. **Gap skip for simple intake** — Always run on mid_goal, or only `complex`?
7. **E1 vs E2** — Ship graph node first, or prototype as two-call inside `plan_assess` for faster validation?
8. **Phase F timing** — Feed gaps to plan-generate on every replan, or only when assess returns `replan`?
9. ~~**Tools in gap**~~ — **Closed:** gap is read-only; IG-394 owns bounded pre-assess tool rounds.
10. ~~**Plan-assess ledger pairs**~~ — **Closed:** amend RFC-214 §3; audit on `GoalNode.last_assessment` (Phase G).
11. **RFC-214 doc update** — Land §3 / §4.3–§4.5 amendments when IG-557 ships?

---

## Files (expected)

```
packages/soothe/src/soothe/foundation/context/models.py
packages/soothe/src/soothe/foundation/context/engine.py
packages/soothe/tests/unit/context/test_goal_last_assessment_ig557.py
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
packages/soothe/tests/unit/core/loop/planning/test_planner_ledger_recording.py
packages/soothe/tests/unit/core/loop/utils/test_ledger_ce_sole_source.py
packages/soothe/tests/integration/core/test_loop_agent_continuation_planning.py
```

---

## Recommended implementation order

```
Phase A (assess projection + envelope) ──┐
Phase G (RFC-214 §3 amend + CE audit)  ──┼── P0
Phase B (guard)                        ──┘
Phase C (PREVIOUS ASSESSMENT)          ─── P1: after G
Phase E (gap analysis, CE audit)       ─── P1
Phase F (gap → generate)               ── P2: replan targeting
```

---

## References

- RFC-206: Prompt architecture (static / semi-static / volatile tiers)
- RFC-214: Loop message surface — **§3, §4.3–§4.5 amended by IG-557 for `call_kind=assess`**
- RFC-220: LangGraph agent loop orchestrator
- RFC-225: Loop continuity and goal record enrichment
- RFC-226: Continuation-aware plan_assess (unchanged path)
- RFC-227: Plan-assess prior-progress digest
- RFC-604: Reason-phase split (`StatusAssessment`)
- RFC-624: Context Engine (`GoalNode`, `LedgerManager`)
- RFC-630: Start-phase LLM intake and branch routing
- IG-555: Plan-assess prior goal completion bias mitigation (iter=0)
- IG-538: Unified planner prompt assembly
- IG-542: Execute-step ledger projection (Slice A/B)
- IG-551: Mid-loop continuation planning coordination
