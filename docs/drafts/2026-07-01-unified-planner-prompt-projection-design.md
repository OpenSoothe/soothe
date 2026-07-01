# Unified Planner Prompt Assembly

**Status**: Draft  
**Date**: 2026-07-01  
**Kind**: Design (Platonic Coding — brainstorm handoff)  
**Related**: RFC-214 (loop message surface — **formalized in §4 / P6**), RFC-225 (loop continuation), RFC-226 (continuation-aware plan_assess), RFC-624 (Context Engine projection)  
**Supersedes behavior in**: ad-hoc branches in `PromptBuilder`, `LLMPlanner.assess_continuation`, `is_continuation_first_plan` ledger skip  

---

## 1. Problem

Planner LLM calls (`continuation_discriminate`, `plan_assess`, `plan_generate`) assemble prompts through **different code paths** with **different rules** for what goes in the ledger vs the final user message.

After multiple goals complete and a new goal starts, behavior diverges:

| Call | Ledger injected? | Cross-goal context |
|------|------------------|-------------------|
| Continuation assess | No — inline string prompt | `PRIOR GOAL COMPLETION` prose in prompt |
| Plan assess | Full ledger (all phases) | No dedicated block |
| Plan generate @ new goal | Ledger **skipped** | `PRIOR GOAL COMPLETION` in envelope |
| Plan generate @ mid-goal | Full ledger | No prior completion block |

This is hard to reason about, duplicates long text (completion report in envelope **and** `goal_completion` ledger rows), and breaks a single mental model for “what the planner sees.”

---

## 2. Constraints (from design discussion)

These are **requirements**, not optional nice-to-haves.

1. **One mental model** — same assembly shape for every planner call; no special-case inline prompts.
2. **Plain prompt text** — keep existing section style (`GOAL:`, `TASK:`, etc.). Simple nested markdown lists where needed. **No** tables, ref IDs (`lm:042`, `g:abc`), or metadata annotations in model-facing text.
3. **Goals referred by label** — use `GOAL: {short description}` to name goals in the envelope, not CE IDs or synthetic refs.
4. **CE is authoritative for structure** — active goal preview, prior goals, steps, status come from Context Engine (+ checkpoint completion when ledger is capped out).
5. **Ledger is authoritative for narrative** — plan turns, execute turns, completion answers live as native Human/AI messages. Do not repeat long bodies in the envelope.
6. **Cache is message-based** — providers cache identical message (or block) content. “Goal boundary” is not a cache primitive. Optimize by **not duplicating text** and keeping system content stable per call kind; put per-call volatility in the **last** HumanMessage only.
7. **Favor ledger projection at new goal** — project prior turns into the message list (with simple phase conditions), instead of skipping ledger and inlining large completion text.
8. **Minimal scope** — no new ref-ID scheme, no “scope” taxonomy, no envelope tables. Two projection modes only.

---

## 3. Design principles

### 3.1 Three parts only

Every planner prompt:

```
[SystemMessage]
[...projected ledger Human/AI turns...]
[LoopHumanMessage — task envelope]
```

### 3.2 Two projection modes only

Derived from loop state — no `continue_loop`, no graph node name, no “scope” enum:

| Mode | Condition |
|------|-----------|
| `new_goal` | `iteration == 0` and no `step_results` |
| `mid_goal` | everything else |

### 3.3 Envelope vs ledger split

| Content | Where it lives |
|---------|----------------|
| Plan / execute / completion **transcripts** | Projected ledger messages |
| Active goal **label** | Envelope: `GOAL:` line (CE preview) |
| Prior goals **structure** (status, steps) | Envelope: `PRIOR GOALS:` nested list at `new_goal` only |
| One-line outcome hint when completion is in ledger | Envelope: `outcome: see prior assistant message` |
| Outcome when ledger capped it out | Envelope: one-line preview from checkpoint |
| Assess / generate **directive** | Envelope: `TASK:` line |

**Rule:** If the text already appears in a projected message above, do not paste it again in the envelope.

### 3.4 Cache guidance (practical, not magical)

- **System prompt**: stable for a given call kind (`assess`, `generate`, `continuation`).
- **Ledger messages**: deterministic projection from CE ledger → same input yields same copied messages (trim only when caps apply).
- **Last HumanMessage**: carries `GOAL:`, `PRIOR GOALS:` tree, `TASK:` — the only part that must change between assess and generate on the same turn.
- **Do not** skip ledger at new goal for “cache” — identical prior messages **are** the cache payload; skipping them removes reusable prefix.

---

## 4. Final proposal

### 4.1 Single entry point

```python
def assemble_planner_prompt(
    *,
    call_kind: Literal["continuation", "assess", "generate"],
    state: LoopState,
    ce: ContextEngine,
    context: PlanContext,
    checkpoint: StrangeLoopCheckpoint | None,
    config: SootheConfig,
) -> list[BaseMessage]:
    mode = "new_goal" if state.iteration == 0 and not state.step_results else "mid_goal"
    system = build_planner_system(call_kind, context, config)
    ledger = project_planner_ledger(ce.ledger, mode, config.agent.loop.plan_prompt_ledger)
    task = build_planner_task_envelope(
        call_kind, mode, state, ce, context, checkpoint, config
    )
    return [
        SystemMessage(content=system),
        *ledger,
        LoopHumanMessage(content=task, phase=_phase_for(call_kind), ...),
    ]
```

**Wiring:**

- `PromptBuilder.build_plan_messages` → thin wrapper (`assess` / `generate`).
- `LLMPlanner.assess_continuation` → `call_kind="continuation"` (delete inline `LOOP_CONTINUATION_ASSESS_PROMPT` HumanMessage path).
- Remove `is_continuation_first_plan` ledger skip in `build_plan_messages`.

### 4.2 Ledger projection

**Function:** extend `project_loop_messages_for_plan` (or CE `LedgerManager.project_for_plan`) with a `mode` argument.

#### `new_goal`

- **Input:** full CE ledger.
- **Phase filter:** `plan_assess`, `plan_generate`, `goal_completion`.
- **Exclude:** `execute_step` by default (outcomes already summarized in `goal_completion` AI messages).
- **Optional config:** `new_goal_include_execute_tail: int` — include last K execute pairs if raw tool evidence is needed at goal start (default `0`).
- **Caps:** existing `PlanPromptLedgerConfig` (tail messages, total chars, per-message chars).

#### `mid_goal`

- **Phase filter:** all phases.
- **Caps:** same as today.

Projection returns a **shallow/deep copy list** of messages; persisted ledger is never mutated (RFC-214 / IG-380 unchanged).

### 4.3 System message

Keep current `PromptBuilder._build_system_message` split:

| Call kind | Instructions fragment |
|-----------|----------------------|
| `continuation` | New small fragment extracted from today’s discriminator criteria (bootstrap vs plan_generate) |
| `assess` | `PLAN_ASSESS_INSTRUCTIONS` |
| `generate` | `EXECUTION_POLICIES` + `PLAN_GENERATE_INSTRUCTIONS` |

Environment, workspace (generate-only workspace rules), context bundle agent/memory instructions — unchanged placement (semi-static at bottom of system).

Capabilities: remain in system for assess/generate; continuation may list capabilities in system or in envelope — **pick system** for consistency and cache stability.

### 4.4 Task envelope format

Keep `_render_sections` / `GOAL:` / `TASK:` plain-text style from `user_message.py`. No new markup conventions.

#### All calls

```text
GOAL:
{CE active goal description, truncated to goal_preview_chars}

TASK:
{call-specific one or two lines}
```

**Task lines:**

| Call kind | TASK |
|-----------|------|
| `continuation` | Decide bootstrap vs plan_generate for this follow-up goal. |
| `assess` | Assess goal completion: return status, goal_progress, assessment_reasoning. |
| `generate` | Generate the execution plan for this goal. |

#### `new_goal` when prior goals exist

Append after `GOAL:`:

```text
PRIOR GOALS:

- GOAL: analyze architecture (completed)
  - 01 explore codebase (completed)
  - 02 write architecture report (completed)
  - outcome: see prior assistant message

- GOAL: review ledger model (completed)
  - 01 read RFC-214 (completed)
  - outcome: Identified three gaps in projection rules…
```

**Population:**

- Tree from CE `GoalStepDAG` (terminal goals, bounded by `max_prior_goals` / `max_steps_per_goal`).
- Step lines: `{id} {description} ({status})`.
- **Outcome line:**
  - If projected ledger includes that goal’s `goal_completion` AI message → `outcome: see prior assistant message`.
  - Else → one-line preview from checkpoint `goal_completion` (truncated).

**Remove** standalone `PRIOR GOAL COMPLETION:` wall-of-text section when completion is in ledger. Keep checkpoint one-liner only as fallback.

**Remove** redundant flat `PRIOR GOALS` / `GOAL LINEAGE` blocks from `ContextBundle` rendering when the tree already covers the same facts (lineage may fold into tree order: oldest → newest).

#### `mid_goal` (assess / generate)

Keep existing blocks unchanged:

- `PRIOR PROGRESS:` (RFC-227 digest)
- `DAG STATUS:` (generate)
- `STEP ID HINT:` (generate)
- `SKILL REFERENCE:` when present

No `PRIOR GOALS:` tree mid-goal — narrative is in ledger tail.

### 4.5 Call matrix

| Call kind | Mode | Ledger phases | Envelope |
|-----------|------|---------------|----------|
| continuation | `new_goal` | plan + generate + goal_completion | GOAL + PRIOR GOALS + TASK |
| assess | `new_goal` | same | same |
| generate | `new_goal` | **same as assess** | same |
| assess | `mid_goal` | all | GOAL + PRIOR PROGRESS + TASK |
| generate | `mid_goal` | all | GOAL + PRIOR PROGRESS + DAG + hints + TASK |

### 4.6 Recording (write path)

Unchanged:

- After assess / generate LLM calls, record compacted human + AI pair to CE ledger (`plan_assess` / `plan_generate` phases).
- Continuation call: **option A (recommended)** — do not record discriminator pair (it is routing, not plan state); **option B** — record as `plan_assess` with a marker. Default **A** to avoid polluting ledger; revisit if audit needs it.

---

## 5. Components touched

| Component | Change |
|-----------|--------|
| `plan_ledger_projection.py` | Add `mode: new_goal \| mid_goal` phase filter |
| `prompts/builder.py` | Delegate to `assemble_planner_prompt`; remove ledger skip |
| `prompts/user_message.py` | `build_planner_task_envelope`; PRIOR GOALS tree renderer; trim `GOAL:` to CE preview |
| `cognition/planner.py` | `assess_continuation` uses assembler |
| `cognition/continuation_prompts.py` | Move criteria into system fragment; deprecate standalone prompt template |
| `engine/continuation_context.py` | Keep `resolve_prior_goal_completion` for fallback one-liner only |
| `config/models.py` | `new_goal_include_execute_tail`, `goal_preview_chars` under `plan_prompt_ledger` or new `plan_envelope` |
| Tests | Mirror `test_builder_continuation_plan_generate` for assess + unified ledger; tree rendering tests |

**Not in scope:** `goal_id` on ledger messages, ref-ID index, CoreAgent projection (unchanged), execute envelope (unchanged).

---

## 6. Before / after example

**Scenario:** Goals A and B completed; new goal C starts (`continue_loop`, iter=0).

### Before (generate)

- Ledger: **empty** (skipped).
- Envelope: full `PRIOR GOAL COMPLETION:` report pasted inline.

### After (generate)

- Ledger: tail of `[… plan/assess, plan/generate, goal_completion pairs for A and B …]` (no execute spam).
- Envelope:

```text
GOAL:
implement the recommended fixes from the architecture review

PRIOR GOALS:

- GOAL: analyze architecture (completed)
  - 01 explore codebase (completed)
  - 02 write architecture report (completed)
  - outcome: see prior assistant message

- GOAL: review module boundaries (completed)
  - 01 compare RFC to code (completed)
  - outcome: see prior assistant message

TASK:
Generate the execution plan for this goal.
```

Assess and continuation on the same turn see the **same ledger prefix**; only system fragment and TASK line differ.

---

## 7. Success criteria

1. All three planner calls use `assemble_planner_prompt` — no inline continuation prompt string.
2. At `new_goal`, assess and generate project **identical** ledger message lists.
3. No `PRIOR GOAL COMPLETION:` block when completion AI turn is present in projected ledger.
4. Envelope uses only plain sections; no tables or synthetic refs in model text.
5. Prior goals rendered as nested list under `PRIOR GOALS:` with `GOAL:` labels.
6. Existing IG-380 caps still apply; no regression in `scripts/verify_finally.sh`.
7. CoreAgent still receives execute-only ledger projection (RFC-214 §3.1 unchanged).

---

## 8. Migration plan

1. Add `project_planner_ledger(mode)` with phase filter — unit tests first.
2. Add `GoalPriorTreeRenderer` (plain list) + `build_planner_task_envelope`.
3. Add `assemble_planner_prompt` and switch `build_plan_messages`.
4. Switch `assess_continuation` to assembler; extract continuation system fragment.
5. Remove `skip_ledger` / `is_continuation_first_plan` ledger bypass for generate.
6. Update tests: `test_builder_continuation_plan_generate`, `test_continuation_assess`, new envelope tree tests.
7. Amend RFC-214 §Plan phase (goal-boundary generate no longer skips ledger; envelope dedup rule). Optionally fold into RFC-226 amendment instead of new RFC.

---

## 9. Open decisions (defaults chosen)

| Question | Default |
|----------|---------|
| Record continuation discriminator in ledger? | No |
| Include execute tail at new goal? | 0 pairs |
| Goal preview length | 120 chars |
| Max prior goals in tree | 5 (reuse `ProjectionConfig.max_goals`) |
| Capabilities in continuation | System message (same as assess) |

---

## 10. Post-draft routing (Platonic Coding)

**Done:** RFC-214 §4 / P6 updated (2026-07-01).

Recommended next step: **Create IG** for implementation tracking, or **implement directly** from RFC-214 §4.

Alternative paths:

1. **Create IG** — `IG-NNN-unified-planner-prompt-assembly.md` for Phase 2 implementation.
2. **Implement directly** — wire `assemble_planner_prompt` per RFC-214 §4.1.
3. **Amend RFC-226** — note continuation prompt template superseded by RFC-214 assembler (relationship §10 updated).

---

## Appendix A — Rejected ideas (intentionally not in design)

- Ref IDs (`lm:001`, `g:abc`) — noise to the model; user rejected.
- Envelope tables and metadata rows — rejected.
- “Scope” taxonomy (`prior_stable_prefix`, `in_goal_narrative`, …) — replaced by two modes.
- Goal-boundary ledger skip for cache — incorrect mental model; message identity matters, not boundary label.
- Full completion report duplicated in envelope when already in ledger — dedup is the main token win.

## Appendix B — Invariants (pin in RFC amend)

1. **Three parts:** system, ledger, task.  
2. **Two modes:** `new_goal`, `mid_goal`.  
3. **Goals named as `GOAL: description` in envelope only.**  
4. **Ledger = narrative; envelope = structure + directive.**  
5. **Plain text sections; nested lists for prior goals when needed.**
