# CoreAgent Clarification Relay — Design Draft

**Date:** 2026-06-02
**Status:** Draft (pre-RFC)
**Author:** Platonic Brainstorming session
**Related:** RFC-220 (AgentLoop), RFC-222 (autopilot mode), `core/loop/engine/graph_interrupt.py`, `core/loop/orchestrator/builder.py`

---

## 1. Problem

When the CoreAgent (deepagents-based LangGraph) emits a clarification question — e.g. *"What specific area or aspect of Soothe would you like to refine, and what's your primary goal for this refinement?"* — the AgentLoop has no relay path back to the originator.

Today, every LangGraph `__interrupt__` chunk surfaced from the CoreAgent stream is silently auto-resumed by `build_auto_resume_payload` in `core/loop/engine/graph_interrupt.py`:

- `type == "ask_user"` interrupts get **empty-string answers** for every question.
- Action-approval interrupts get auto-`approve`.

The empty answers cause the model to spin: it replans, asks again, gets another empty answer, and the loop wastes iterations. In the captured trace (`trace-2626ed6b65d86c80845248e42f383bff.json`), three consecutive `plan_generate` / `plan_assess` cycles produced empty model outputs — the signature of this bug.

There is also no concept of a "clarification-pending" loop state, so the AgentLoop graph cannot route, persist, or surface the question to a human or to a programmatic answerer.

## 2. Goals

- When CoreAgent emits a clarification, the AgentLoop relays it through a policy layer and resumes CoreAgent with a real answer.
- Two policy implementations:
  - **Manual mode**: relay to a human via the TUI, block durably until they answer.
  - **Auto mode**: delegate to a new `veritas` subagent that auto-answers from goal intent and global context; may defer if it can't.
- Policy is selectable per runtime mode without forcing `GoalEngine` into solo AgentLoop runs.
- Loop pause for human input is checkpointable so daemon restart / TUI close-reopen resumes cleanly.

## 3. Non-goals

- Action-approval HITL (the `type=="review"` flow). Stays on auto-approve until a future iteration.
- Cross-loop or cross-goal clarifications (one loop asking another).
- Reshaping LangGraph interrupt internals or `deepagents.HumanInTheLoopMiddleware`.
- A general "operator dashboard"; we emit events that a future dashboard can consume.

## 4. Architecture overview

Four new pieces:

1. **`ClarificationPolicy` protocol** in `core/loop/clarification/` — injected via `LoopRuntimeContext`.
2. **`await_clarification` graph node** in the AgentLoop topology (RFC-220 delta) — durable pause point.
3. **`veritas` subagent** in `subagents/veritas/` — intent-grounded auto-answerer used by `AutoClarificationPolicy`.
4. **TUI mode toggle** (Manual ↔ Auto) with a status-line indicator and `--mode` CLI flag.

```
                       ┌───────────────────────┐
   CoreAgent.astream() │   inside execute /    │
   emits interrupt     │   plan_generate /     │
   {"type":"ask_user"} │   plan_assess node    │
                       └──────────┬────────────┘
                                  │ (interrupt detected
                                  │  by stream wrapper)
                                  ▼
                   set LoopGraphState.pending_clarification
                                  │
                                  ▼
                       ┌───────────────────────┐
                       │ await_clarification   │
                       │ (new node)            │
                       │ calls policy.answer() │
                       └──────────┬────────────┘
                                  │
                         ┌────────┴─────────┐
                         │                  │
              Manual: loop-level   Auto: veritas
              interrupt() blocks   subagent answers
              for TUI answer       (or sets defer=True)
                         │                  │
                         └────────┬─────────┘
                                  ▼
              pending_clarification_answer → resume CoreAgent
              with Command(resume={"answers": [...]})
```

## 5. Detection: what counts as a "clarification"?

CoreAgent can emit clarifications in two shapes:

**(a) Structured interrupt (primary path).**
A `LangGraph.interrupt({"type": "ask_user", "questions": [...]})` chunk. Already surfaced today at `core/loop/engine/graph_interrupt.py:51`. We replace the empty-answer payload with `ClarificationPolicy.answer(...)` output.

**(b) Plain assistant question text (fallback path).**
The model ends a turn with a question and no tool call. The CoreAgent stream simply terminates; the loop assumes "done" and routes to `record_iteration` or `plan_assess`, which sees no progress and replans.

**Plan:**

- Encourage CoreAgent to use a structured marker. Add a thin `ask_clarification` tool (or system-prompt directive that wraps the question in `<clarification>...</clarification>`) so detection is deterministic.
- Add a `ClarificationDetector` that runs on the final assistant message of every CoreAgent stream. If no tool calls were emitted and the message contains a clarification marker (or matches a simple heuristic: trailing `?` plus an intent cue like "would you like", "which", "what"), synthesize an `ask_user`-equivalent request and route through the same policy path.

Heuristic detection is intentionally a fallback — structured-marker path is what we drive callers toward.

## 6. `ClarificationPolicy` protocol

New package: `packages/soothe/src/soothe/core/loop/clarification/`.

```python
# protocol.py
from __future__ import annotations
from typing import Any, Literal, Protocol

@dataclass(frozen=True)
class ClarificationRequest:
    questions: list[str]
    origin_node: str               # "execute" | "plan_generate" | "plan_assess"
    origin_interrupt_id: str       # LangGraph interrupt id (or synthetic)
    loop_state_snapshot: "LoopStateView"   # read-only projection

@dataclass(frozen=True)
class ClarificationAnswer:
    answers: list[str]             # one per question, parallel to request.questions
    source: Literal["human", "veritas", "fallback"]
    confidence: float | None       # auto answers only
    defer: bool = False            # if True, policy is signalling "pause goal, ask human later"
    audit: dict[str, Any] = field(default_factory=dict)

class ClarificationPolicy(Protocol):
    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer: ...
```

Two built-ins under `core/loop/clarification/`:

- **`InteractiveClarificationPolicy`** — emits a `soothe.loop.clarification_requested` event and calls LangGraph `interrupt(...)` at the loop level (so the loop graph itself pauses durably). On resume the TUI's `Command(resume=...)` payload carries the answer.
- **`AutoClarificationPolicy`** — invokes the `veritas` subagent. If `veritas` returns `defer=True` (low confidence / can't answer), the policy raises `ClarificationDeferred` which the `await_clarification` node catches and translates to the loop-pause + `awaiting_clarification` goal status.

Injection:

- `LoopRuntimeContext.clarification_policy: ClarificationPolicy` is set when the runtime builds the context.
- Default selection:
  - Solo CLI interactive (stdin is a TTY, no `--mode auto`): `InteractiveClarificationPolicy`.
  - Solo CLI `--mode auto` or non-TTY: `AutoClarificationPolicy`.
  - Autopilot daemon: `AutoClarificationPolicy` (GoalEngine may supply a subclass with goal-aware overrides).
- TUI Manual ↔ Auto toggle hot-swaps the policy on the live `LoopRuntimeContext`. In-flight clarifications complete under the policy that was active when they were emitted.

`GoalEngine` is **not** introduced into the solo loop. The policy abstraction is what travels.

## 7. `await_clarification` graph node

### 7.1 Topology delta

Three new conditional edges and one new node added to `core/loop/orchestrator/builder.py`:

```
execute             → route_after_execute       → {record_iteration, await_clarification, END}
plan_generate       → route_after_plan          → {goal_completion, resolve_decision, await_clarification}
plan_assess         → route_after_assess        → {goal_completion, resolve_decision, plan_generate, await_clarification}
await_clarification → route_after_clarification → {execute, plan_generate, plan_assess}
                                                  (routes back to origin_node)
```

The router after each existing node checks `state.pending_clarification`; if set, it routes to `await_clarification` instead of its normal target.

### 7.2 State additions

`LoopGraphState` (in `core/loop/orchestrator/state.py`):

```python
pending_clarification: ClarificationRequest | None
pending_clarification_answer: ClarificationAnswer | None
last_clarification_origin: Literal["execute", "plan_generate", "plan_assess"] | None
```

`last_clarification_origin` is set by the originating node's stream wrapper at the same time it sets `pending_clarification`. `route_after_clarification` uses it to route back to the right node after the answer is collected.

### 7.3 Node behavior

```python
async def node_await_clarification(ctx, state):
    request = state["pending_clarification"]
    policy = ctx.clarification_policy
    await ctx.emit("clarification_requested", {
        "questions": request.questions,
        "origin": request.origin_node,
    })
    try:
        answer = await policy.answer(request)
    except ClarificationDeferred as e:
        # mark_goal_status is a new helper on LoopRuntimeContext that proxies to
        # the persistence backend (GoalEngine in autopilot, AgentLoopStateManager in solo).
        await ctx.mark_goal_status("awaiting_clarification", reason=str(e))
        await ctx.emit("clarification_deferred", {...})
        return {"pending_clarification": None, "terminate": True}

    await ctx.emit("clarification_answered", {
        "source": answer.source,
        "defer": answer.defer,
        "confidence": answer.confidence,
    })
    return {
        "pending_clarification": None,
        "pending_clarification_answer": answer,
    }
```

### 7.4 Resume into CoreAgent

When `plan_generate` / `plan_assess` / `execute` is re-entered after `await_clarification`, the stream wrapper sees `pending_clarification_answer` is set and builds the resume payload:

```python
resume_payload = {request.origin_interrupt_id: {"answers": answer.answers}}
current_input = Command(resume=resume_payload)
# clear pending_clarification_answer after use
```

`_core_agent_astream_with_interrupt_resume` is restructured: it no longer auto-resumes `ask_user` interrupts. Instead it returns control to the node, which sets `pending_clarification` on state and exits; the router sends control to `await_clarification`; on return, the node re-enters and resumes with the real payload.

### 7.5 Durability

Because `InteractiveClarificationPolicy.answer()` uses LangGraph `interrupt(...)` at the loop graph level, the AgentLoop's checkpointer captures the pause. TUI close + reopen, or daemon restart, restores the loop at `await_clarification` and the operator can still answer. No bespoke persistence needed beyond the existing checkpoint store.

### 7.6 Goal status

When `AutoClarificationPolicy` raises `ClarificationDeferred` (i.e. veritas returns `defer=True`), the loop:

- Sets the goal's status to `awaiting_clarification` (new value on the goal-status enum).
- Persists the pending question on goal state.
- Stops iterating. Scheduler skips it until an out-of-band answer arrives (`soothe goal answer <id> "..."` CLI, or operator dashboard).

When `InteractiveClarificationPolicy` is in use, the goal stays `running`; the AgentLoop is simply paused on the graph interrupt.

## 8. `veritas` subagent

Currently `packages/soothe/src/soothe/subagents/veritas/__init__.py` is empty. We build it out as the Auto-mode answerer.

### 8.1 Role

Veritas is **not** a full CoreAgent. It is a focused subagent that answers a clarification "as the originating user would," grounded in:

- **First-principles slice**: original user goal text, intent classification, top-level `plan.goal_description` — stripped of execution noise.
- **Global context**: workspace tree summary, recent step outputs (last N, configurable), known constraints (skills activated, MCP servers, policy denials).

It returns a structured `ClarificationAnswer` (one string per question) plus a `defer` flag.

### 8.2 Module layout

```
subagents/veritas/
├── __init__.py
├── events.py           # soothe.subagent.veritas.{requested,answered,deferred}
├── implementation.py   # CompiledSubAgent factory
├── prompts.py          # system prompt: "answer as the user would, from goal intent"
└── schemas.py          # VeritasAnswerSchema (Pydantic, structured output)
```

### 8.3 Schema

```python
class VeritasAnswerSchema(BaseModel):
    answers: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    defer: bool = False
    rationale: str          # short explanation, for audit
```

### 8.4 Model resolution

Use `config.create_chat_model("clarification")` — new role, defaults to the same model as `plan_assess` if unset. Adding a role (vs. hard-wiring `plan_assess`) lets users tune veritas independently.

### 8.5 Confidence thresholding

`AutoClarificationPolicy` treats `confidence < 0.4` (configurable: `agent.clarification.auto_min_confidence`) as if `defer=True`. Defaults give the policy a safety net even if veritas forgets to defer.

### 8.6 No looping

Veritas itself never emits clarifications (its system prompt forbids it; any clarification-shaped output is treated as `defer=True`). This avoids recursive clarification.

## 9. TUI Manual/Auto toggle

- **Keybind**: `ctrl+m` toggles Manual ↔ Auto. Shift+Tab keeps its current job (loop selector).
- **Status line**: `[manual]` (green) or `[auto]` (yellow) badge in the persistent status row.
- **CLI flag**: `soothe --mode {manual,auto}` for one-shot runs. Default: `manual` when stdin is a TTY, `auto` otherwise. Autopilot ignores the flag.
- **Hot swap**: toggle replaces `LoopRuntimeContext.clarification_policy` for future requests. In-flight requests finish under the prior policy.
- **Event surfacing**: a `clarification_requested` event in Manual mode pops a modal in the TUI showing the question(s) and capturing the answer; on submit, the TUI sends `Command(resume=...)` to the loop graph.

## 10. Module map summary

| New / changed | Path |
|---|---|
| **new** | `packages/soothe/src/soothe/core/loop/clarification/protocol.py` |
| **new** | `packages/soothe/src/soothe/core/loop/clarification/interactive.py` |
| **new** | `packages/soothe/src/soothe/core/loop/clarification/auto.py` |
| **new** | `packages/soothe/src/soothe/core/loop/clarification/detector.py` |
| **new** | `packages/soothe/src/soothe/core/loop/orchestrator/nodes/await_clarification.py` |
| **new** | `packages/soothe/src/soothe/subagents/veritas/{events,implementation,prompts,schemas}.py` |
| **edit** | `packages/soothe/src/soothe/core/loop/engine/graph_interrupt.py` — keep helpers, drop empty-answer default |
| **edit** | `packages/soothe/src/soothe/core/loop/engine/executor.py` — `_core_agent_astream_with_interrupt_resume` returns to node on `ask_user`, resumes with real payload on re-entry |
| **edit** | `packages/soothe/src/soothe/core/loop/orchestrator/builder.py` — add `await_clarification` node + routes |
| **edit** | `packages/soothe/src/soothe/core/loop/orchestrator/routing.py` — `route_after_*` checks `pending_clarification` first |
| **edit** | `packages/soothe/src/soothe/core/loop/orchestrator/state.py` — add `pending_clarification*` fields |
| **edit** | `packages/soothe/src/soothe/core/loop/orchestrator/runtime_context.py` — add `clarification_policy` field |
| **edit** | `packages/soothe/src/soothe/core/goal_engine/...` — add `awaiting_clarification` status + `answer_clarification(goal_id, ...)` API |
| **edit** | `packages/soothe-cli/src/soothe_cli/tui/app/_messages_mixin.py` — `ctrl+m` action, status-line badge |
| **edit** | `packages/soothe-cli/src/soothe_cli/cli/main.py` — `--mode` flag plumbed to runtime |
| **edit** | `config/config.template.yml` + `config/config.dev.yml` — new `agent.clarification.*` settings |

## 11. Events (RFC-600 register_event)

New event types:

- `soothe.loop.clarification_requested` — fired when `await_clarification` enters. Payload: `questions`, `origin_node`, `mode`.
- `soothe.loop.clarification_answered` — fired after policy returns. Payload: `source`, `confidence`, `defer`.
- `soothe.loop.clarification_deferred` — fired when policy raises `ClarificationDeferred`. Payload: `reason`, `question_summary`.
- `soothe.subagent.veritas.requested` / `.answered` / `.deferred` — standard subagent lifecycle.

All registered via `register_event(...)` in the owning module's `events.py`.

## 12. Configuration additions

```yaml
agent:
  clarification:
    auto_policy: veritas          # only built-in for now
    auto_min_confidence: 0.4      # below this, veritas answer is treated as defer
    max_defer_age_hours: 168      # autopilot only: scrub stale awaiting_clarification goals
    detector:
      enable_heuristic: true
      heuristic_intent_cues:
        - "would you like"
        - "which"
        - "what specific"
        - "could you clarify"

  veritas:
    model_role: clarification
    max_context_steps: 8          # how many recent step outputs to include
```

Both `config.template.yml` and `config.dev.yml` updated together (mandatory project rule).

## 13. Testing

Unit:
- `tests/unit/core/loop/clarification/test_protocol.py` — request/answer schemas.
- `tests/unit/core/loop/clarification/test_interactive.py` — TUI relay through fake event bus.
- `tests/unit/core/loop/clarification/test_auto.py` — veritas mock returning answer / defer / low confidence.
- `tests/unit/core/loop/clarification/test_detector.py` — structured marker + heuristic detection.
- `tests/unit/core/loop/orchestrator/nodes/test_await_clarification.py` — node behavior, deferred path.
- `tests/unit/core/loop/orchestrator/test_routing.py` — extended for `pending_clarification` short-circuit.
- `tests/unit/subagents/veritas/test_implementation.py` — schema enforcement, defer path, no clarification recursion.
- Update `tests/unit/core/loop/engine/test_graph_interrupt.py` to assert policy dispatch (no more empty-answer assertions).

Integration:
- `tests/integration/core/loop/test_clarification_relay.py` — full graph round-trip: CoreAgent emits `ask_user` → `await_clarification` → policy answers → CoreAgent resumes → final output produced.
- `tests/integration/core/loop/test_clarification_durable_pause.py` — Manual mode: pause at `await_clarification`, simulate checkpointer restart, resume with answer.

## 14. Migration & risk

- **Behavior change**: solo CLI no longer silently empty-answers `ask_user`. Manual mode now blocks for input; Auto mode now calls veritas. This is the intent — we're fixing the bug — but it is a visible behavior delta.
- **Test impact**: existing `build_auto_resume_payload` tests need rewriting. Action-approval auto-approve is preserved unchanged.
- **Veritas wrongness**: a buggy veritas could answer incorrectly. Mitigations: every answer emits an audit event with question + answer + source + confidence + rationale; `confidence < threshold` triggers defer; `awaiting_clarification` defer path is always available.
- **Durability**: pause-on-human requires the AgentLoop checkpointer. Already on by default; doctor check confirms presence.
- **Autopilot scheduler**: must learn `awaiting_clarification` is "blocked, not active." One-line change in concurrency accounting.

## 15. Open items for RFC formalization

- Exact name + structure of the structured `ask_clarification` marker / tool (vs. relying on existing `interrupt` shape only).
- Concrete goal-status enum location and migration story for existing persisted goals.
- Whether `--mode auto` for a one-shot CLI should fall back to TUI relay if no `veritas` is configured (degraded mode) — currently we'd error out at startup.
- How `veritas` interacts with the workspace trust model — does it need read access to files it summarizes, or is the loop's pre-built summary sufficient?

These are intentionally left for Phase 1 RFC + `specs-refine`.

---
