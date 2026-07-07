# IG-460: CoreAgent Clarification Relay

**RFC**: [RFC-622](../specs/RFC-622-coreagent-clarification-relay.md)
**Status**: Draft
**Created**: 2026-06-02
**Lineage**: Extends [IG-451](IG-451-hitl-remnants-cleanup.md) — IG-451 removed the legacy `AskUserMenu` widget and `resume_interrupts` protocol because no real relay existed. IG-460 introduces a proper policy-driven relay (`ClarificationPolicy` + `await_clarification` graph node + `veritas` subagent + TUI mode toggle).
**Depends on**: RFC-220 (loop graph), RFC-222 (autopilot), RFC-600 (`register_event`), RFC-601 (built-in subagents), RFC-403 (event naming).

---

## 1. Goal

Replace `build_auto_resume_payload`'s empty-string answers for `ask_user` interrupts with a real relay path:

- **Manual mode (TUI)**: question pops a modal; loop pauses durably; operator answers; CoreAgent resumes.
- **Auto mode (autopilot or `--mode auto`)**: `veritas` subagent answers from goal intent + global context; loop defers the goal to `awaiting_clarification` if confidence is too low.
- **Plain-text question fallback**: detector synthesizes an `ask_user`-equivalent so unstructured clarifications also relay.

No `GoalEngine` in the solo loop. Policy is injected via `LoopRuntimeContext`.

---

## 2. Module layout

### 2.1 New packages

```
packages/soothe/src/soothe/core/loop/clarification/
├── __init__.py
├── protocol.py           # ClarificationPolicy + dataclasses + ClarificationDeferred
├── interactive.py        # InteractiveClarificationPolicy (TUI relay, loop-level interrupt)
├── auto.py               # AutoClarificationPolicy (veritas delegate + confidence gate)
├── detector.py           # ClarificationDetector (structured `ask_user` only)
├── events.py             # soothe.loop.clarification.* event registration
└── selector.py           # build_default_clarification_policy(mode, runtime) → ClarificationPolicy

packages/soothe/src/soothe/subagents/veritas/
├── __init__.py           # public exports
├── events.py             # soothe.subagent.veritas.* event registration
├── implementation.py     # async answer(request, ctx) → VeritasAnswerSchema
├── prompts.py            # system prompt (no-clarification, intent voice)
└── schemas.py            # VeritasAnswerSchema (Pydantic)
```

### 2.2 New orchestrator node

```
packages/soothe/src/soothe/core/loop/orchestrator/nodes/
└── await_clarification.py    # node_await_clarification(ctx, state)
```

### 2.3 Changed files

| File | Change |
|------|--------|
| `core/loop/orchestrator/state.py` | Add `pending_clarification`, `pending_clarification_answer`, `last_clarification_origin` to `LoopGraphState`. |
| `core/loop/orchestrator/runtime_context.py` | Add `clarification_policy: ClarificationPolicy` field; add `mark_goal_status(status, reason)` helper. |
| `core/loop/orchestrator/routing.py` | Each `route_after_execute`/`route_after_plan`/`route_after_assess` short-circuits to `"await_clarification"` if `state.get("pending_clarification")`. Add `route_after_clarification`. |
| `core/loop/orchestrator/builder.py` | Register `await_clarification` node; add edges; update conditional-edge maps. |
| `core/loop/engine/graph_interrupt.py` | `build_auto_resume_payload` keeps action-approval auto-approve only; remove the `ask_user` branch. |
| `core/loop/engine/executor.py` | `_core_agent_astream_with_interrupt_resume` no longer auto-resumes `ask_user`. On detection it sets `state.pending_clarification` and returns; on re-entry it consumes `state.pending_clarification_answer` and resumes with the real payload. |
| `core/goal_engine/...` | Add `awaiting_clarification` to the goal-status enum; add `answer_clarification(goal_id, answers)` API. Concurrency accounting excludes `awaiting_clarification`. |
| `cli/main.py` | `--mode {manual,auto}` flag, default `manual` if TTY else `auto`. |
| `cli/tui/app/_messages_mixin.py` | `ctrl+m` binding for mode toggle. |
| `cli/tui/app/_app.py` | Mode badge in status line. |
| `cli/tui/widgets/clarification_modal.py` | **new** modal that displays the question(s) and dispatches `Command(resume=…)` back to the loop. |
| `cli/runtime/transport/session.py` | New `clarification_response` outbound message + handler. |
| `config/config.template.yml`, `config/develop/config.yml` | New `agent.clarification.*` and `agent.veritas.*` sections (both files updated, per project rule). |

### 2.4 Tests

Per project rule, tests live in package-specific dirs.

```
packages/soothe/tests/unit/core/loop/clarification/
├── test_protocol.py
├── test_interactive.py
├── test_auto.py
├── test_detector.py
└── test_selector.py

packages/soothe/tests/unit/core/loop/orchestrator/nodes/
└── test_await_clarification.py

packages/soothe/tests/unit/core/loop/orchestrator/
└── test_routing.py               # extend existing tests with pending_clarification short-circuit

packages/soothe/tests/unit/subagents/veritas/
└── test_implementation.py

packages/soothe/tests/unit/core/loop/engine/
└── test_graph_interrupt.py       # rewrite — assert ask_user no longer auto-empty

packages/soothe/tests/integration/core/loop/
├── test_clarification_relay.py
└── test_clarification_durable_pause.py
```

---

## 3. Concrete type definitions

### 3.1 `clarification/protocol.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ClarificationOrigin = Literal["execute", "plan_generate", "plan_assess"]


@dataclass(frozen=True)
class LoopStateView:
    """Read-only projection of LoopState passed to clarification policies.

    Intentionally narrow — policies should not mutate or learn loop internals.
    """

    goal_id: str
    goal_description: str
    user_request: str
    iteration: int
    intent_classification: str | None
    plan_summary: str | None
    recent_step_outputs: list[str]
    workspace_summary: str | None
    active_skills: list[str]
    active_mcp_servers: list[str]


@dataclass(frozen=True)
class ClarificationRequest:
    questions: list[str]
    origin_node: ClarificationOrigin
    origin_interrupt_id: str          # LangGraph interrupt id
    loop_state: LoopStateView


@dataclass(frozen=True)
class ClarificationAnswer:
    answers: list[str]                # parallel to request.questions
    source: Literal["human", "veritas", "fallback"]
    confidence: float | None = None
    defer: bool = False
    audit: dict[str, Any] = field(default_factory=dict)


class ClarificationDeferred(Exception):
    """Raised by a policy when no answer is available; await_clarification translates
    to ``awaiting_clarification`` goal status + loop termination."""

    def __init__(self, reason: str, request: ClarificationRequest) -> None:
        super().__init__(reason)
        self.reason = reason
        self.request = request


class ClarificationPolicy(Protocol):
    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer: ...
```

### 3.2 `clarification/interactive.py` (sketch)

```python
class InteractiveClarificationPolicy:
    def __init__(self, emit: EmitFn) -> None:
        self._emit = emit

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        from langgraph.types import interrupt          # loop-level interrupt

        await self._emit(
            "clarification_requested",
            {
                "questions": request.questions,
                "origin": request.origin_node,
                "mode": "manual",
            },
        )
        payload = interrupt(
            {
                "type": "clarification",
                "interrupt_id": request.origin_interrupt_id,
                "questions": request.questions,
            }
        )
        answers = list(payload.get("answers", []))
        if len(answers) != len(request.questions):
            # tolerate single-answer payloads by broadcasting
            if len(answers) == 1:
                answers = answers * len(request.questions)
            else:
                raise ClarificationDeferred("answer count mismatch", request)
        return ClarificationAnswer(answers=answers, source="human")
```

### 3.3 `clarification/auto.py` (sketch)

```python
class AutoClarificationPolicy:
    def __init__(
        self,
        veritas_answer: Callable[[ClarificationRequest], Awaitable["VeritasAnswerSchema"]],
        *,
        min_confidence: float = 0.4,
    ) -> None:
        self._veritas = veritas_answer
        self._min_confidence = min_confidence

    async def answer(self, request: ClarificationRequest) -> ClarificationAnswer:
        result = await self._veritas(request)
        if result.defer or result.confidence < self._min_confidence:
            raise ClarificationDeferred(
                f"veritas defer (confidence={result.confidence:.2f}, defer={result.defer})",
                request,
            )
        return ClarificationAnswer(
            answers=result.answers,
            source="veritas",
            confidence=result.confidence,
            audit={"rationale": result.rationale},
        )
```

### 3.4 `clarification/detector.py`

```python
class ClarificationDetector:
    def from_interrupt(
        self,
        value: Mapping[str, Any],
        *,
        interrupt_id: str,
        origin_node: ClarificationOrigin,
        loop_state: LoopStateView,
    ) -> ClarificationRequest | None:
        """Return request if value is a structured ask_user interrupt, else None.

        Plain-text questions are intentionally not detected; emit a
        structured ``interrupt({"type": "ask_user", ...})`` to engage the relay.
        """
```

### 3.5 `subagents/veritas/schemas.py`

```python
from pydantic import BaseModel, Field


class VeritasAnswerSchema(BaseModel):
    answers: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    defer: bool = False
    rationale: str = ""
```

### 3.6 `subagents/veritas/implementation.py` (sketch)

```python
async def answer(
    request: ClarificationRequest,
    *,
    model: BaseChatModel,
    max_context_steps: int = 8,
) -> VeritasAnswerSchema:
    structured = model.with_structured_output(VeritasAnswerSchema)
    system = build_veritas_system_prompt()                 # in prompts.py
    user = build_veritas_user_prompt(request, max_context_steps)
    result = await structured.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])
    # Safety net: any question-shaped answer collapses to defer.
    if any(answer.strip().endswith("?") for answer in result.answers):
        return result.model_copy(update={"defer": True, "confidence": 0.0})
    return result
```

### 3.7 `LoopGraphState` additions (`orchestrator/state.py`)

```python
class LoopGraphState(TypedDict, total=False):
    # …existing fields…
    pending_clarification: dict[str, Any] | None          # serialized ClarificationRequest
    pending_clarification_answer: dict[str, Any] | None   # serialized ClarificationAnswer
    last_clarification_origin: ClarificationOrigin | None
```

Serialized form (rather than dataclass) because LangGraph channel values must be JSON-serializable for checkpointing. Helper functions in `protocol.py`:

```python
def request_to_state(req: ClarificationRequest) -> dict[str, Any]: ...
def request_from_state(d: Mapping[str, Any]) -> ClarificationRequest: ...
def answer_to_state(ans: ClarificationAnswer) -> dict[str, Any]: ...
def answer_from_state(d: Mapping[str, Any]) -> ClarificationAnswer: ...
```

### 3.8 `LoopRuntimeContext` addition (`orchestrator/runtime_context.py`)

```python
@dataclass
class LoopRuntimeContext:
    # …existing fields…
    clarification_policy: ClarificationPolicy | None = None

    async def mark_goal_status(self, status: str, reason: str = "") -> None:
        # Solo: writes via StrangeLoopStateManager
        # Autopilot: GoalEngine subclass overrides to also notify scheduler
        ...
```

### 3.9 `orchestrator/routing.py` (sketch — additions)

```python
def _pending_clarification(state: dict[str, Any]) -> bool:
    return bool(state.get("pending_clarification"))

def route_after_execute(state: dict[str, Any]) -> str:
    if _pending_clarification(state):
        return "await_clarification"
    if state.get("last_outcome") == "fatal":
        return END
    return "record_iteration"

def route_after_plan(state: dict[str, Any]) -> str:
    if _pending_clarification(state):
        return "await_clarification"
    if state.get("plan_route") == PLAN_ROUTE_GOAL_DONE:
        return "goal_completion"
    return "resolve_decision"

def route_after_assess(state: dict[str, Any]) -> str:
    if _pending_clarification(state):
        return "await_clarification"
    # …existing logic…

def route_after_clarification(state: dict[str, Any]) -> str:
    if state.get("last_outcome") == "deferred":
        return END
    origin = state.get("last_clarification_origin")
    if origin in ("execute", "plan_generate", "plan_assess"):
        return origin
    return END    # fail-safe
```

### 3.10 `orchestrator/builder.py` deltas

```python
from .nodes.await_clarification import node_await_clarification
from .routing import route_after_clarification

# …

graph.add_node("await_clarification", await_clarification)

graph.add_conditional_edges(
    "execute",
    route_after_execute,
    {
        "record_iteration": "record_iteration",
        "await_clarification": "await_clarification",
        END: END,
    },
)
graph.add_conditional_edges(
    "plan_generate",
    route_after_plan,
    {
        "goal_completion": "goal_completion",
        "resolve_decision": "resolve_decision",
        "await_clarification": "await_clarification",
    },
)
graph.add_conditional_edges(
    "plan_assess",
    route_after_assess,
    {
        "goal_completion": "goal_completion",
        "resolve_decision": "resolve_decision",
        "plan_generate": "plan_generate",
        "await_clarification": "await_clarification",
    },
)
graph.add_conditional_edges(
    "await_clarification",
    route_after_clarification,
    {
        "execute": "execute",
        "plan_generate": "plan_generate",
        "plan_assess": "plan_assess",
        END: END,
    },
)
```

### 3.11 `nodes/await_clarification.py`

```python
async def node_await_clarification(ctx, state):
    policy = ctx.clarification_policy
    if policy is None:
        # mis-configured runtime: defer immediately
        ...

    request = request_from_state(state["pending_clarification"])
    try:
        answer = await policy.answer(request)
    except ClarificationDeferred as e:
        await ctx.mark_goal_status("awaiting_clarification", reason=str(e))
        await ctx.emit("clarification_deferred", {
            "reason": str(e),
            "question_summary": _summary(request.questions),
        })
        return {
            "pending_clarification": None,
            "pending_clarification_answer": None,
            "last_outcome": "deferred",
        }

    await ctx.emit("clarification_answered", {
        "source": answer.source,
        "confidence": answer.confidence,
        "defer": answer.defer,
    })
    return {
        "pending_clarification": None,
        "pending_clarification_answer": answer_to_state(answer),
    }
```

### 3.12 `executor.py` rewrite of stream wrapper

```python
async def _core_agent_astream_with_interrupt_resume(
    self,
    stream_input,
    graph_config,
    *,
    detector: ClarificationDetector,
    state_setter: Callable[[dict[str, Any]], None],
    state_getter: Callable[[], dict[str, Any]],
):
    interrupt_iterations = 0
    current_input = stream_input

    # First, consume any pending answer from a prior await_clarification visit.
    pending_answer = state_getter().get("pending_clarification_answer")
    if pending_answer:
        origin_id = pending_answer["audit"].get("interrupt_id") or state_getter()["pending_clarification_meta"]["origin_interrupt_id"]
        current_input = Command(resume={origin_id: {"answers": pending_answer["answers"]}})
        state_setter({"pending_clarification_answer": None})

    while True:
        interrupt_occurred = False
        chunk_iter = self.core_agent.astream(
            current_input, config=graph_config,
            stream_mode=["messages", "updates", "custom"], subgraphs=True,
        )
        async for chunk in chunk_iter:
            ...
            if mode == "updates" and "__interrupt__" in data:
                for iobj in data["__interrupt__"]:
                    req = detector.from_interrupt(iobj.value)
                    if req is None:
                        # action-approval style → keep auto-approve
                        current_input = Command(resume=build_auto_resume_payload({iobj.id: iobj.value}))
                        interrupt_occurred = True
                        break
                    state_setter({
                        "pending_clarification": request_to_state(
                            replace(req, origin_interrupt_id=iobj.id)
                        ),
                        "last_clarification_origin": _origin_for_current_node(),
                    })
                    return     # bubble up; await_clarification node will resume
            yield chunk

        if not interrupt_occurred:
            return     # no ask_user interrupt — stream completed normally

        interrupt_iterations += 1
        if interrupt_iterations > _MAX_INTERRUPT_ITERATIONS:
            return
```

(The exact API for `state_setter` / `state_getter` is established by the caller node; the simplest implementation just collects pending updates into a dict that the node returns.)

### 3.13 Event types (`clarification/events.py`)

```python
LOOP_CLARIFICATION_REQUESTED = "soothe.loop.clarification.requested"
LOOP_CLARIFICATION_ANSWERED  = "soothe.loop.clarification.answered"
LOOP_CLARIFICATION_DEFERRED  = "soothe.loop.clarification.deferred"

class ClarificationRequestedEvent(SootheEvent):
    type: Literal[LOOP_CLARIFICATION_REQUESTED] = LOOP_CLARIFICATION_REQUESTED
    questions: list[str] = []
    origin_node: str = ""
    mode: Literal["manual", "auto"] = "manual"

class ClarificationAnsweredEvent(SootheEvent):
    type: Literal[LOOP_CLARIFICATION_ANSWERED] = LOOP_CLARIFICATION_ANSWERED
    source: Literal["human", "veritas", "fallback"] = "human"
    confidence: float | None = None
    defer: bool = False

class ClarificationDeferredEvent(SootheEvent):
    type: Literal[LOOP_CLARIFICATION_DEFERRED] = LOOP_CLARIFICATION_DEFERRED
    reason: str = ""
    question_summary: str = ""

register_event(ClarificationRequestedEvent, ...)
register_event(ClarificationAnsweredEvent, ...)
register_event(ClarificationDeferredEvent, ...)
```

Equivalent pattern under `subagents/veritas/events.py` for `soothe.subagent.veritas.{requested,answered,deferred}`.

### 3.14 Config additions

```yaml
# config/config.template.yml (and matching defaults in config/develop/config.yml)
agent:
  clarification:
    auto_policy: veritas
    auto_min_confidence: 0.4
    max_defer_age_hours: 168
  veritas:
    model_role: think
    max_context_steps: 8
```

Veritas reuses the existing ``"think"`` ``ModelRole`` — no new role is introduced.

---

## 4. Build order

1. **Schemas + protocol** (`clarification/protocol.py`, `subagents/veritas/schemas.py`). No imports of higher layers. Unit-testable in isolation.
2. **Detector** (`clarification/detector.py`). Pure logic over `BaseMessage` + interrupt dicts.
3. **Events** (`clarification/events.py`, `subagents/veritas/events.py`). Register at module-load.
4. **Veritas implementation** (`subagents/veritas/implementation.py`, `prompts.py`). Pure async function depending only on a `BaseChatModel`.
5. **Auto policy** (`clarification/auto.py`). Composes veritas function + confidence gate.
6. **Interactive policy** (`clarification/interactive.py`). Uses LangGraph `interrupt(...)`.
7. **Selector** (`clarification/selector.py`). `build_default_clarification_policy(mode, runtime)`.
8. **State + runtime context** (`orchestrator/state.py`, `runtime_context.py`). Add fields. Backward-compatible since `total=False`.
9. **Routing** (`orchestrator/routing.py`). Add short-circuits + new router. Update existing tests.
10. **`await_clarification` node** (`orchestrator/nodes/await_clarification.py`).
11. **Builder** (`orchestrator/builder.py`). Wire node + edges.
12. **Executor stream wrapper** (`engine/executor.py`, `engine/graph_interrupt.py`). Replace auto-empty.
13. **Goal engine status enum + API** (`core/goal_engine/...`). Add `awaiting_clarification` + `answer_clarification` + concurrency exclusion.
14. **CLI flag** (`cli/main.py`). `--mode {manual,auto}`.
15. **TUI** (`cli/tui/...`). Modal, mode badge, `ctrl+m` binding, response transport.
16. **`soothe goal answer` CLI** (`cli/commands/...`). Out-of-band answer for deferred goals.
17. **Config files** (`config/config.template.yml`, `config/develop/config.yml`). Both updated.
18. **Tests** alongside each step.
19. **Verification**: `./scripts/verify_finally.sh`.

---

## 5. Test plan (concrete)

| File | Cases |
|------|-------|
| `test_protocol.py` | dataclass equality, `(de)serialize` round-trip, `ClarificationDeferred` carries request. |
| `test_detector.py` | structured `ask_user` matched (list and singular forms); non-`ask_user` interrupt returns None; empty/whitespace-only questions rejected; non-mapping values rejected. |
| `test_interactive.py` | with a stub `interrupt(...)` that returns `{"answers": ["foo"]}`, returns `ClarificationAnswer(source="human", answers=["foo"])`. Answer-count mismatch → `ClarificationDeferred`. |
| `test_auto.py` | stub veritas returning confidence=0.9 → answer; confidence=0.1 → `ClarificationDeferred`; `defer=True` → `ClarificationDeferred`. |
| `test_selector.py` | TTY + no flag → interactive; `--mode auto` → auto; autopilot → auto regardless. |
| `test_await_clarification.py` | success path returns answer + clears pending; `ClarificationDeferred` sets `last_outcome="deferred"` + emits event. |
| `test_routing.py` (extended) | each `route_after_*` returns `"await_clarification"` when `pending_clarification` set; `route_after_clarification` returns origin; deferred outcome → END. |
| `test_graph_interrupt.py` (rewritten) | `build_auto_resume_payload` no longer handles `ask_user`; still auto-approves action-approval style. |
| `test_implementation.py` (veritas) | high-confidence answer; defer when answer ends with `?`; structured output parsing. |
| `test_clarification_relay.py` (integration) | inject CoreAgent stub that emits `ask_user`; manual mode round-trip returns answer; auto mode round-trip via stub veritas returns answer. |
| `test_clarification_durable_pause.py` (integration) | manual mode pauses at `await_clarification`; new graph instance with same checkpointer resumes from the same point and accepts a `Command(resume=…)`. |

Coverage target: `ClarificationPolicy` protocol implementations and `await_clarification` node ≥ 90%; detector ≥ 85%.

---

## 6. Verification

```bash
./scripts/verify_finally.sh   # format-check + lint (zero errors) + 900+ unit tests
```

Spot-checks beyond the script:

- `soothe doctor` — confirm new config keys validate.
- Manual sanity run: `soothe -p "refine the auth module"` (vague prompt) → TUI modal appears with the clarification, accept input, observe CoreAgent resume.
- Auto sanity run: `soothe --mode auto -p "refine the auth module"` → veritas answers from goal text; loop proceeds without pausing.

---

## 7. Rollout

- **Phase A (this IG)**: full implementation behind `agent.clarification.auto_policy: veritas`. Default mode: `manual` for TTY, `auto` for non-TTY (matches current operator habits).
- **Phase B (next IG)**: structured `ask_clarification` tool registered as a built-in tool with clear docs in `prompts/project_instructions.py` so models reach for it whenever they need to ask the user.
- **Phase C (later)**: operator dashboard surface for `awaiting_clarification` goals (out of scope here).

---

## 8. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Veritas hallucinates an answer | Confidence floor + audit event with full rationale; deferred path always available. |
| Plain-text detector false positive halts the loop unnecessarily | Heuristic is conservative (requires trailing `?` + intent cue); user can disable via `enable_heuristic: false`. |
| Existing tests break (auto-empty assumption) | `test_graph_interrupt.py` rewritten; CI catches anything else. |
| Loop-level `interrupt(...)` checkpoint shape changes between LangGraph versions | Wire only through the `langgraph.types.interrupt` public API; pin via existing `pyproject.toml`. |
| TUI modal blocks other interactions | Modal is push-screen-style; user can `Esc` to defer (treated as `ClarificationDeferred`). |

---

## 9. Out of scope (deferred)

- Action-approval HITL.
- Multi-goal cross-clarifications.
- Veritas using tools (filesystem reads etc.) — Phase A is pure-LLM with provided context.
- Operator dashboard UI.

---

## 10. Status

Draft — awaiting implementation.
