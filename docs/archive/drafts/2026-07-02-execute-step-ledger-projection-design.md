# Execute-Step Ledger Projection

**Status**: Draft  
**Date**: 2026-07-02  
**Kind**: Design (Platonic Coding — brainstorm handoff)  
**Related**: RFC-214 (loop message surface §3.1), RFC-223 (thread fork / branch isolation), RFC-225 (loop continuation), RFC-226 (continuation bootstrap), RFC-227 (prior progress digest), IG-477 (per-step `__step_<id>` threads), IG-538 (unified planner projection), IG-540 (intake prior-goal projection)  
**Companion**: `docs/drafts/2026-07-01-unified-planner-prompt-projection-design.md` (planner-side symmetry)  
**Supersedes behavior in**: envelope-only `PRIOR STEP EVIDENCE`, inline-only `PRIOR GOAL COMPLETION` on bootstrap, ad-hoc `project_predecessor_execute_ledger_for_step` without cross-goal slice  

---

## 1. Problem

CoreAgent execute-step runs on **isolated branch threads** (`{logical}__step_{step_id}`) with **empty checkpoints**. The orchestration ledger (`LoopState.loop_messages`) holds the full loop history, but graph input today is assembled **asymmetrically** compared to planner prompts:

| Boundary | What matters | Current execute projection |
|----------|--------------|----------------------------|
| **Cross-goal** (prior goals on same loop thread) | How each prior goal **ended** (completion) | Bootstrap only: inline `PRIOR GOAL COMPLETION` text; **no** ledger replay. Later steps in the new goal get **nothing** from prior goals. |
| **Intra-goal** (DAG `dependencies`) | Predecessor **execute** evidence | Transitive-predecessor `execute_step` Human/AI replay + lightweight `PRIOR STEPS` envelope. |

Planner prompts already solved the cross-goal side at `new_goal` (IG-538): project `goal_completion` ledger turns, dedupe inline completion prose. Execute-step never got the same treatment.

Within a multi-goal loop, prior goals can end in **two valid completion shapes**:

1. **Synthesized** — `phase=goal_completion` Human/AI pair appended after synthesis.
2. **Ledger-direct** — no `goal_completion` rows; the **last** `execute_step` Human/AI pair for that goal *is* the terminal answer (`CompletionStrategy.LEDGER_DIRECT`).

Intake classification already resolves a single prior goal with this order (`project_prior_goal_completion_for_intake`). Execute-step needs the same resolution, extended to **K prior goals**, injected as native ledger messages — not duplicated inline blocks.

---

## 2. Constraints (from design discussion)

These are **requirements**.

1. **Two boundaries, two slices** — cross-goal completions vs intra-goal execute deps; do not conflate them.
2. **Mirror planner mental model** — same “project ledger + lightweight envelope metadata” split as IG-538 / unified planner draft.
3. **No duplication** — if completion or execute evidence is in projected `messages[]`, do not paste the same body in the envelope (IG-538 dedup rule).
4. **Branch isolation preserved** — each step still runs on `__step_<id>`; projection **replaces** checkpoint history for that branch, it does not fork checkpoints.
5. **Slice A always K** — at goal boundary, **always** attempt `K` prior-goal completion units (config default `K=1`); project all available when fewer than K exist; never pad.
6. **Dual completion types in Slice A** — synthesized `goal_completion` pairs **and** ledger-direct last `execute_step` pairs are both valid; resolve **per prior goal**, not with a single global phase filter.
7. **Do not replay full prior-goal execute history in Slice A** — only the terminal completion unit per goal (compression same as planner `new_goal` excluding execute tail).
8. **Intra-goal slice stays narrow** — transitive predecessor `execute_step` rows only; no sibling steps, no plan-phase rows.
9. **Minimal scope** — no `goal_id` on ledger messages in P0 (use checkpoint `goal_history` + ledger scan); no new ref-ID scheme.

---

## 3. Design principles

### 3.1 Three parts only

Every execute-step CoreAgent call:

```
[SystemMessage + middleware-injected context]
[...Slice A: cross-goal completion units (0–2K messages)...]
[...Slice B: intra-goal predecessor execute_step pairs...]
[LoopHumanMessage — current execute envelope (Slice C)]
```

Persisted orchestration ledger remains append-only and unchanged; projection is **read-side** only.

### 3.2 Two execute projection modes

Parallel to planner `new_goal` / `mid_goal`:

| Mode | Condition | Slice A | Slice B |
|------|-----------|---------|---------|
| `goal_boundary` | `iteration == 0` and no `step_results` on active goal | **Always K** completion units | If step has deps |
| `intra_goal` | after first execution in goal | — | If step has deps |
| `solo` | no deps and not at goal boundary | — | — |

`goal_boundary` requires prior goals on the loop thread (`continue_loop` or checkpoint `goal_history` non-empty). First goal on a fresh loop: Slice A is empty (K=0 effectively).

### 3.3 Envelope vs ledger split

| Content | Where it lives |
|---------|----------------|
| Prior goal **completion transcripts** (synthesized or ledger-direct) | Slice A — projected Human/AI pairs |
| Predecessor **execute** transcripts (same goal) | Slice B — projected Human/AI pairs |
| Current step task + hints | Slice C — envelope |
| Prior goal **structure** (desc + status) | Slice C — `PRIOR GOALS:` tree at boundary (optional, lightweight) |
| Prior step **structure** (desc + status) | Slice C — `PRIOR STEPS:` when deps |
| Long completion prose | **Not** in envelope when Slice A projected |

**Rule:** If the text already appears in a projected message above, do not paste it again in the envelope.

---

## 4. Slice A — cross-goal completion tail (K units)

### 4.1 Policy

Whenever mode is `goal_boundary`, **always** call:

```python
project_cross_goal_completion_tail(
    loop_messages,
    checkpoint,
    k=config.execute_prompt_ledger.cross_goal_completion_tail,  # default 1
    ledger_cfg=config.agent.loop.plan_prompt_ledger,  # shared caps
) -> list[BaseMessage]
```

Output: up to **`2 × K`** messages (Human+AI per prior goal), **chronological order** (oldest goal first).

### 4.2 One completion unit per prior goal

For each prior goal segment, resolve **one** terminal pair:

```python
def resolve_goal_completion_unit(segment: list[BaseMessage]) -> list[BaseMessage]:
    # 1. Synthesized (preferred)
    pair = extract_last_phase_pair(segment, "goal_completion")
    if pair:
        return pair

    # 2. Ledger-direct — last execute_step pair in this goal's segment
    pair = extract_last_phase_pair(segment, "execute_step")
    if pair:
        return pair  # keep phase=execute_step; semantic role = goal completion

    return []
```

**Do not** rewrite `phase` on ledger-direct pairs. Envelope/metadata may label them as prior-goal outcomes; native turns preserve audit truth.

**Excluded from Slice A:** full prior-goal execute history, `plan_assess` / `plan_generate` tails, `plan_direct` narration.

### 4.3 Segmenting prior goals (K walk)

Walk completed goals **newest → oldest**, stop at K.

**Primary source:** `checkpoint.goal_history` (authoritative goal list on loop thread).

For each prior goal record:

1. Prefer ledger slice bounded to that goal (when segmentable).
2. Run `resolve_goal_completion_unit(segment)`.
3. Fallback: checkpoint `goal_completion` text → minimal stub pair only if ledger segment is empty (same as `resolve_prior_goal_completion` today).

**Fallback when checkpoint sparse:** scan `loop_messages` backward; detect boundaries at:

- `goal_completion` AI (+ Human partner), or
- ledger-direct terminal `execute_step` pair before next new-goal plan boundary (`plan_assess` at `iteration == 0`).

Reuse `_extract_last_phase_pair` from `plan_ledger_projection.py` (IG-540 / intake path).

### 4.4 Envelope dedup at boundary

When Slice A is non-empty:

| Envelope section | Action |
|------------------|--------|
| `PRIOR GOAL COMPLETION` | **Omit** |
| `PRIOR GOALS` | Optional tree: `GOAL: {desc} ({status})` + `outcome: see prior assistant message` per prior goal (mirrors plan `new_goal`) |

When Slice A is empty but continuation context exists (caps trimmed everything): keep capped `PRIOR GOAL COMPLETION` inline fallback.

---

## 5. Slice B — intra-goal predecessor execute projection

Unchanged intent from current shipped behavior; tighten scope:

- Filter: `phase == "execute_step"` AND `step_id ∈ transitive_dependencies(step, decision)`.
- Order: ledger append order.
- Cap: `predecessor_max_messages` (default 96).
- **Scope guard (P1):** prefer rows whose `step_id` appears in `decision.steps`; when `goal_id` exists on ledger entries (future), restrict to active goal.

Envelope: `PRIOR STEPS` — desc + status only; `outcome: see prior assistant message`.

**Not in Slice B:** cross-goal completion units (Slice A handles those at boundary only).

---

## 6. Slice C — current execute envelope

Stable section order:

```
EXECUTION TASK:
...

PRIOR STEPS:          # when dependencies (intra-goal metadata)
...

PRIOR GOALS:          # at goal boundary when Slice A projected (metadata only)
...

EXECUTION HINTS:
...
```

Optional: `SKILL CONTEXT`, `MCP RESOURCES`, `WORKSPACE STATE`.

Recorded ledger compaction (`compact_execute_human_content`) continues to store **EXECUTION TASK + EXPECTED OUTPUT** only — volatile envelope sections and projected slices are not persisted on the Human row.

---

## 7. Combined scenarios

| Scenario | Mode | Slice A (K units) | Slice B | Envelope C |
|----------|------|-------------------|---------|------------|
| First goal, root step | `solo` | — | — | task + hints |
| First goal, dependent step | `intra_goal`* | — | pred execute rows | task + `PRIOR STEPS` |
| Goal B bootstrap, no deps | `goal_boundary` | **K** completion pairs | — | task + hints; no inline `PRIOR GOAL COMPLETION` |
| Goal B first wave, with deps | `goal_boundary` | **K** completion pairs | pred execute rows | task + `PRIOR STEPS` |
| Goal B mid-goal root | `solo` | — | — | task + hints |
| Goal B mid-goal dependent | `intra_goal` | — | pred execute rows | task + `PRIOR STEPS` |
| Loop with 3 prior goals, new goal | `goal_boundary` | **min(3, K)** pairs | per deps | optional `PRIOR GOALS` tree |
| Prior goal synthesized, next ledger-direct | `goal_boundary` | mixed pair types in one tail | per deps | metadata only |

\*First goal with deps before any `step_results`: mode is `goal_boundary` but Slice A empty; Slice B applies.

---

## 8. API sketch

Single entry point (symmetric with `assemble_planner_prompt`):

```python
def project_execute_step_graph_input(
    *,
    loop_messages: list[BaseMessage],
    state: LoopState,
    step: StepAction,
    decision: AgentDecision,
    checkpoint: StrangeLoopCheckpoint | None,
    cfg: ExecutePromptLedgerConfig,
) -> list[BaseMessage]:
    mode = resolve_execute_projection_mode(state, step)
    out: list[BaseMessage] = []

    if mode == "goal_boundary":
        out.extend(
            project_cross_goal_completion_tail(
                loop_messages,
                checkpoint=checkpoint,
                k=cfg.cross_goal_completion_tail,
                ledger_cfg=cfg.ledger_caps,
            )
        )

    if mode in ("goal_boundary", "intra_goal") and (step.dependencies or []):
        out.extend(
            project_predecessor_execute_ledger_for_step(
                loop_messages, step, decision,
                max_messages=cfg.predecessor_max_messages,
            )
        )

    return out
```

Executor wiring:

```python
graph_input_messages = project_execute_step_graph_input(...)
envelope = compose_execute_step_envelope(..., slice_a_projected=bool(slice_a))
graph_input_messages.append(LoopHumanMessage(content=envelope, phase="execute_step"))
```

Replace direct calls to `project_predecessor_execute_ledger_for_step` in `_execute_step_collecting_events`.

### New / moved helpers

| Function | Module | Role |
|----------|--------|------|
| `resolve_execute_projection_mode` | `plan_ledger_projection.py` | `goal_boundary` / `intra_goal` / `solo` |
| `project_cross_goal_completion_tail` | `plan_ledger_projection.py` | Slice A — K units, dual completion resolution |
| `resolve_goal_completion_unit` | `plan_ledger_projection.py` | Per-goal synthesized vs ledger-direct |
| `segment_ledger_by_prior_goals` | `plan_ledger_projection.py` or `continuation_context.py` | Checkpoint-driven K walk |
| `project_execute_step_graph_input` | `plan_ledger_projection.py` | Orchestrator |
| `render_prior_goals_tree` / `PRIOR STEPS` | `user_message.py` | Envelope metadata (existing) |

---

## 9. Configuration

```yaml
agent:
  loop:
    execute_prompt_ledger:
      cross_goal_completion_tail: 1   # K — always attempted at goal_boundary
      predecessor_max_messages: 96
    plan_prompt_ledger:               # shared tail/char caps for Slice A+B
      max_messages: 0
      max_total_chars: 0
      max_per_message_chars: 0
```

Add to `config.template.yml` + `config/develop/config.yml` when implementing.

---

## 10. Edge cases

| Case | Behavior |
|------|----------|
| `K=3`, only 1 prior goal | Project 1 unit (≤2 messages) |
| Prior goal synthesized + next ledger-direct | Each unit resolved independently |
| Ledger-direct goal with many execute steps | Unit = **last** execute_step pair only |
| Slice A capped by char limit | Fall back to inline `PRIOR GOAL COMPLETION` for trimmed tail |
| `loop_state is None` / no `current_decision` | No projection (test harness); logical thread only |
| Mid-goal dependent step | Slice A off; Slice B only |
| `quiz` terminal (intake fallback) | **Out of scope** for execute Slice A unless product requires quiz→goal handoff |

---

## 11. Migration from current state

| Current | Target |
|---------|--------|
| Inline `PRIOR GOAL COMPLETION` on bootstrap | Slice A ledger + deduped envelope |
| `project_predecessor_execute_ledger_for_step` only | Slice B inside `project_execute_step_graph_input` |
| `PRIOR STEPS` envelope metadata | Keep (Slice C) |
| RFC-214 §3.1 “envelope-only PRIOR STEP EVIDENCE” | **Superseded** by this design (ledger projection + metadata) |
| `build_prior_step_evidence()` | Retain for P2 brief hydration only |

Update RFC-214 §3.1 and IG-536-dependent-step when formalizing.

---

## 12. Acceptance criteria

1. At `goal_boundary`, execute graph input **always** includes up to K prior-goal completion units (synthesized or ledger-direct per goal).
2. Ledger-direct prior goals project as native last `execute_step` Human/AI pairs without phase rewriting.
3. When Slice A is non-empty, execute envelope **omits** inline `PRIOR GOAL COMPLETION`.
4. Dependent steps receive Slice B transitive-predecessor execute rows + `PRIOR STEPS` metadata; no sibling cross-talk.
5. Mid-goal root steps receive neither Slice A nor Slice B.
6. `./scripts/verify_finally.sh` passes after implementation.

---

## 13. Phased delivery

| Phase | Scope |
|-------|-------|
| **P0** | `project_cross_goal_completion_tail`, mode resolution, executor wiring, envelope dedup, tests mirroring intake dual-resolution cases |
| **P1** | Intra-goal scope guard; shared trim with `plan_prompt_ledger`; config sync |
| **P2** | `goal_id` on ledger entries; CE `project_for_core_agent` delegates to unified projector |

---

## 14. Open questions (for RFC / IG formalization)

1. Default **K**: `1` (token-safe) vs `3` (long loop threads)?
2. **`PRIOR GOALS` tree** at execute boundary: required or optional when Slice A already projected?
3. **Checkpoint vs ledger** when they disagree on completion body — prefer checkpoint (today) or ledger-first?

---

## Post-draft routing (Platonic Coding)

Related existing artifacts:

| Artifact | Relationship |
|----------|----------------|
| **RFC-214** §3.1 | **Update** — execute projection rules supersede envelope-only dependent-step text |
| **IG-536-dependent-step-prompt-grounding** | **Update** — P0/P1 completion projection |
| **IG-538** / unified planner draft | **Align** — symmetric cross-goal completion handling |
| New **IG-5xx** | **Create** if implement before RFC edit |

Recommended next step: **(4) Create a new IG** from this draft for P0 implementation, then **(3) Update RFC-214** §3.1 when behavior ships.

Alternative paths:

1. Pause at each phase gate — approve IG before coding  
2. Quick pass — implement P0 directly from this draft  
3. Update RFC-214 first, then IG  
4. Create new RFC (only if RFC-214 edit scope feels too large)  
5. Update IG-536-dependent-step in place  
6. Create new IG-5xx execute-step-ledger-projection  
