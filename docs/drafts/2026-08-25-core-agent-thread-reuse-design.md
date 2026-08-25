# CoreAgent Thread Reuse and Interrupt Resume — Design Draft

**Status:** Proposed (design draft — pending user review)
**Date:** 2026-08-25
**Scope:** `soothe.sloop.engine.execute` thread selection, checkpointer, interrupt resume

## 1. Problem

The CoreAgent execute step creates an **isolated thread per step** (`{loop_id}__step_{step_id}`), compiled on an **ephemeral twin graph with `checkpointer=None`**. This has three consequences:

1. **No checkpoint persistence** — the ephemeral twin doesn't persist state, so `Command(resume=...)` after an `ask_user` interrupt is a no-op.
2. **Thread_id tied to step_id** — when DISPATCH re-creates a step (new ID), the thread_id changes. Even with a checkpointer, the old thread's checkpoint is unreachable.
3. **No context reuse between linear steps** — each step starts fresh. Predecessor context flows via ledger projection (text), not checkpoint inheritance. A 5-step linear chain re-reads the codebase 5 times.

## 2. Design Principles

- **Decoupled thread_id**: thread_id is a random 5-digit + loop_id, NOT derived from step_id. Stored in `LoopState.step_thread_ids[step.id]` so it can be recovered.
- **Selective reuse**: reuse the parent's thread only when the dependency structure is strictly linear (single parent, single child) or when resuming after an interrupt.
- **No infinite accumulation**: because thread_id is not fixed to `__root`, a new thread is created whenever the structure branches or context is full. Long loops don't accumulate.
- **Interrupt resume**: when a step triggers `ask_user`/interrupt, the thread_id MUST be reused on resume so `Command(resume=...)` finds the pending interrupt.

## 3. Proposed Design

### 3.1 Thread ID Generation (decoupled from step_id)

Thread_id format: `{loop_id}__{random_5digits}` (e.g. `01a03943__7f3a2`).

Generated once per step, stored in `LoopState.step_thread_ids[step.id]`. If the same step_id is re-executed (after reactivation), the stored thread_id is reused. If a new step_id is created (DISPATCH fallback), a new thread_id is generated.

```python
import secrets

def _generate_thread_id(main_thread_id: str) -> str:
    """Generate a random thread_id decoupled from step_id."""
    suffix = secrets.token_hex(5)[:5]  # 5 hex chars
    return f"{main_thread_id}__{suffix}"
```

### 3.2 Thread Reuse Policy

Reuse the parent step's thread_id **only** when one of these conditions holds:

**Condition A — Strict linear chain**:
- The step has exactly 1 dependency (single parent)
- The parent step has exactly 1 child (this step is its only successor)
- → The chain is linear: parent → this step, no fan-out

**Condition B — Interrupt resume**:
- The step is being resumed after an `ask_user` or `action_requests` interrupt
- → Must reuse the exact thread_id that was active when the interrupt fired
- The thread_id is recovered from `LoopState.step_thread_ids[step.id]` (or from the `pending_clarification` state which carries the origin interrupt_id)

**All other cases** (parallel siblings, fan-in, root step, context overflow):
- Generate a new thread_id

```python
def _select_thread_for_step(
    step: StepAction,
    main_thread_id: str,
    *,
    decision: AgentDecision,
    loop_state: LoopState,
    is_clarification_resume: bool = False,
) -> str:
    # Condition B: interrupt resume — must reuse the original thread
    if is_clarification_resume:
        prior = loop_state.step_thread_ids.get(step.id)
        if prior:
            return prior
        # Step ID changed (DISPATCH re-creation); try to recover from
        # the pending_clarification state's origin thread_id
        origin_tid = getattr(loop_state, "_resume_thread_id", None)
        if origin_tid:
            return origin_tid

    # Condition A: strict linear chain — reuse parent's thread
    if step.dependencies and len(step.dependencies) == 1:
        parent_id = step.dependencies[0]
        parent_thread = loop_state.step_thread_ids.get(parent_id)
        if parent_thread and _is_only_child(parent_id, decision):
            return parent_thread

    # Default: new isolated thread
    return _generate_thread_id(main_thread_id)


def _is_only_child(parent_id: str, decision: AgentDecision) -> bool:
    """True when parent_id has exactly one child in the decision's step list."""
    children = [s for s in decision.steps if parent_id in (s.dependencies or [])]
    return len(children) == 1
```

### 3.3 Interrupt Thread Recovery

When an `ask_user` interrupt fires, the executor stores the thread_id on the `pending_clarification` state (or a new `_resume_thread_id` field on `LoopState`) so it can be recovered on resume even if the step_id changed:

```python
# In executor.py, when capturing the GraphInterrupt:
if capture.pending_request is not None:
    # Store the thread_id for resume recovery
    loop_state._resume_thread_id = fork_thread_id
```

On resume in `node_execute`, the `is_clarification_resume=True` path reads `_resume_thread_id` from `LoopState` and reuses it. This works even when DISPATCH creates a new step (new ID) — the thread_id is independent of step_id.

### 3.4 Checkpointer on the Execute Twin

Compile the ephemeral twin **with** the shared checkpointer (`_compile_deep_agent(cp)`). This enables:
- `Command(resume=...)` to find the pending interrupt on the stored thread_id
- Thread reuse to inherit the parent's checkpoint state (messages, tool results)
- `durability="exit"` controls write frequency

### 3.5 Resume Path (no DISPATCH)

On `ask_user` resume (`decision is None`, `resume_answer_payload is not None`):
1. Recover the original thread_id from `LoopState._resume_thread_id`
2. Rebuild a minimal `AgentDecision` from the CE root step
3. Set `ctx.scratch.decision` and `ctx.scratch.plan_result`
4. Fall through to the normal Executor with `is_clarification_resume=True`
5. Executor uses the recovered thread_id → checkpointer has the pending interrupt
6. `Command(resume=...)` re-enters at the ToolNode → `ask_user` returns the answer
7. Step completes → no DISPATCH, no new step, no re-asking

## 4. Architecture

```
Step DAG:
  Root (thread A) → Step2 (reuses A, linear) → Step3 (thread B, fan-out)
                                                 ↓
                                          Step4 (thread C, parallel sibling)

  Root (thread A) → ask_user interrupt → pause
  Resume: recover thread A → Command(resume=...) → step completes on thread A
```

## 5. Trade-offs

### Random thread_id vs. deterministic

**Pro**: Thread_id survives step re-creation (not derived from step_id). New steps get new threads — no accumulation.

**Con**: Can't predict the thread_id from the step_id alone. Mitigated by `LoopState.step_thread_ids` mapping.

### Linear thread reuse

**Pro**: A 5-step linear chain reuses thread A for steps 1-2, then forks to B when context fills. Steps 2-5 inherit accumulated file reads/search results from step 1.

**Con**: Context grows. Mitigated by the strict single-parent-single-child condition — only true linear chains reuse. Fan-out or fan-in always gets a new thread. ContextWindowManager handles compaction when the thread fills.

### Interrupt resume

**Pro**: `ask_user` tool interrupt correctly resumes on the original thread. No re-asking.

**Con**: Requires the checkpointer on the execute twin (slight I/O overhead). Mitigated by `durability="exit"`.

## 6. Implementation Files

| File | Change |
|---|---|
| `soothe-nano/agent/builder.py:324` | `_compile_deep_agent(cp)` — twin shares the checkpointer |
| `soothe/sloop/engine/execute/thread_selection.py` | New: random thread_id + linear reuse + interrupt resume policy |
| `soothe/sloop/state/schemas.py` | Add `_resume_thread_id: str \| None` to `LoopState` |
| `soothe/sloop/engine/execute/executor.py` | Store `fork_thread_id` on `loop_state._resume_thread_id` when capturing interrupt; pass `is_clarification_resume` to `_select_thread_for_step` |
| `soothe/sloop/stations/execute/execute.py` | Resume path: rebuild decision from CE, fall through to Executor with `is_clarification_resume=True` |
