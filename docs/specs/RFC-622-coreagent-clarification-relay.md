# RFC-622: CoreAgent Clarification Relay

**RFC**: 622  
**Title**: CoreAgent Clarification Relay  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-06-02  
**Authors**: Soothe Team  
**Depends on**: RFC-220 (Agentic Goal Execution / StrangeLoop), RFC-222 (Autopilot Mode), RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)  
**Supersedes**: Empty-answer auto-resume behavior currently encoded in `core/loop/engine/graph_interrupt.py::build_auto_resume_payload` for `type=="ask_user"` interrupts.

---

## 1. Abstract

When the **CoreAgent** (deepagents-based LangGraph) emits a clarification — e.g. *"What specific area or aspect of Soothe would you like to refine?"* — the surrounding **StrangeLoop** silently auto-resumes the interrupt with empty-string answers. The model receives no useful input, replans into a spin, and burns iterations.

This RFC introduces a **clarification relay**: a `ClarificationPolicy` protocol, a dedicated `await_clarification` graph node in the StrangeLoop, two built-in policies (interactive TUI relay and auto-answer), a new `veritas` subagent that answers clarifications as the originating user would, and a TUI Manual/Auto mode toggle. The pause-on-human path is durable via the existing LangGraph checkpointer.

The relay works identically in solo StrangeLoop and autopilot runs **without** forcing `GoalEngine` into solo mode: policy is injected through `LoopRuntimeContext`.

---

## 2. Scope

### 2.1 In scope

- `ClarificationPolicy` protocol and two built-in implementations.
- `await_clarification` StrangeLoop graph node and routing changes.
- `LoopGraphState` additions for pending clarification + answer + origin.
- `veritas` subagent (intent-grounded auto-answerer) under `subagents/veritas/`.
- TUI Manual ↔ Auto toggle, status badge, and `--mode` CLI flag.
- Detection of structured `ask_user` LangGraph interrupts. Plain-text questions in assistant messages are intentionally **not** detected; callers that want to ask the user must emit a structured interrupt.
- New goal status `awaiting_clarification` and a CLI/API to answer deferred clarifications out-of-band.
- New event types `soothe.loop.clarification_*` and `soothe.subagent.veritas.*`.
- `agent.clarification.*` and `agent.veritas.*` configuration additions in both `config/config.template.yml` and `config/develop/nano.yml`.

### 2.2 Non-goals

- Action-approval HITL (`type=="review"` interrupts) — current auto-approve behavior is preserved.
- Cross-loop or cross-goal clarifications.
- Operator dashboard UI beyond CLI events.
- Restructuring LangGraph interrupt primitives or `deepagents.HumanInTheLoopMiddleware`.

---

## 3. Motivation

| Issue (current behavior) | Relay response |
|--------------------------|----------------|
| `ask_user` interrupts auto-resumed with `""` answers (`graph_interrupt.py:47`) | Policy-driven payload from real human or auto-answerer |
| StrangeLoop has no graph state for "paused on human" | First-class `pending_clarification` state + dedicated node |
| Solo StrangeLoop has no GoalEngine; autopilot does | `ClarificationPolicy` protocol injected via `LoopRuntimeContext`; runtimes pick their implementation |
| No way for an operator to see/answer questions out-of-band | `awaiting_clarification` goal status + `soothe goal answer` CLI |
| Plain-text clarifications (no tool call, no `interrupt`) silently end turns | Heuristic detector synthesizes an equivalent request |

The bug is reproducible in trace `trace-2626ed6b65d86c80845248e42f383bff.json`: three consecutive `plan_generate`/`plan_assess` cycles produce empty model outputs after the model asks *"What specific area or aspect of Soothe would you like to refine?"*.

---

## 4. Architecture

### 4.1 Component overview

```
                          ┌─────────────────────────────┐
   CoreAgent.astream()    │ Stream wrapper:              │
   inside execute /       │  _core_agent_astream_with_   │
   plan_generate /        │  interrupt_resume            │
   plan_assess            └─────────────┬───────────────┘
                                        │
                          ┌─────────────┴───────────────┐
                          │ ClarificationDetector        │
                          │ - structured ask_user only   │
                          └─────────────┬───────────────┘
                                        │
                               set state.pending_clarification
                                        │
                                        ▼
                          ┌─────────────────────────────┐
                          │ StrangeLoop graph router       │
                          │ short-circuits to:           │
                          │   await_clarification        │
                          └─────────────┬───────────────┘
                                        │
                          ┌─────────────────────────────┐
                          │ await_clarification node     │
                          │ → ClarificationPolicy        │
                          └─────────────┬───────────────┘
                          ┌─────────────┴───────────────┐
                          ▼                              ▼
            InteractiveClarificationPolicy   AutoClarificationPolicy
                  (TUI relay,                   (veritas subagent;
                   loop-level interrupt,         defer if low confidence)
                   durable checkpoint)
                          │                              │
                          └─────────────┬───────────────┘
                                        │
                        state.pending_clarification_answer
                                        │
                          ┌─────────────▼───────────────┐
                          │ route_after_clarification    │
                          │ → originating node           │
                          └─────────────┬───────────────┘
                                        │
                          CoreAgent resumed with
                          Command(resume={"answers": [...]})
```

### 4.2 New components

| Component | Path | Responsibility |
|-----------|------|----------------|
| `ClarificationPolicy` protocol | `core/loop/clarification/protocol.py` | Abstract interface; request/answer dataclasses |
| `InteractiveClarificationPolicy` | `core/loop/clarification/interactive.py` | TUI relay; loop-level `interrupt(...)` for durability |
| `AutoClarificationPolicy` | `core/loop/clarification/auto.py` | Delegates to `veritas`; enforces min-confidence; raises `ClarificationDeferred` |
| `ClarificationDetector` | `core/loop/clarification/detector.py` | Recognizes structured ``ask_user`` interrupts |
| `await_clarification` node | `core/loop/orchestrator/nodes/await_clarification.py` | Calls policy; emits audit events; updates state |
| `veritas` subagent | `subagents/veritas/{__init__,events,implementation,prompts,schemas}.py` | Intent-grounded auto-answerer; structured output via Pydantic |

### 4.3 Changed components

| File | Change |
|------|--------|
| `core/loop/engine/graph_interrupt.py` | Drop empty-answer default for `ask_user`; helpers stay |
| `core/loop/engine/executor.py` | `_core_agent_astream_with_interrupt_resume` returns to node on `ask_user` instead of auto-resuming; resumes with real payload on re-entry |
| `core/loop/orchestrator/builder.py` | Add `await_clarification` node + edges |
| `core/loop/orchestrator/routing.py` | Each `route_after_*` short-circuits to `await_clarification` if `pending_clarification` is set |
| `core/loop/orchestrator/state.py` | Add `pending_clarification`, `pending_clarification_answer`, `last_clarification_origin` |
| `core/loop/orchestrator/runtime_context.py` | Add `clarification_policy: ClarificationPolicy` |
| `core/goal_engine/*` | Add `awaiting_clarification` status + `answer_clarification(goal_id, ...)` API |
| `cli/tui/app/_messages_mixin.py` | `ctrl+m` action; mode status badge |
| `cli/main.py` | `--mode {manual,auto}` flag plumbed to runtime |
| `config/config.template.yml`, `config/develop/nano.yml` | New `agent.clarification.*` and `agent.veritas.*` sections |

---

## 5. Data Flow

### 5.1 Flow 1: Interactive clarification (Manual mode)

1. CoreAgent emits `interrupt({"type":"ask_user", "questions":[...]})` inside `execute`.
2. Stream wrapper sees the chunk, sets `state.pending_clarification` and `state.last_clarification_origin = "execute"`, exits the stream loop without auto-resume.
3. `execute` node returns; `route_after_execute` detects `pending_clarification` and routes to `await_clarification`.
4. `await_clarification` calls `InteractiveClarificationPolicy.answer(request)`, which:
   - Emits `soothe.loop.clarification_requested`.
   - Calls LangGraph `interrupt(loop_request)` at the loop level → checkpoint snapshotted.
   - Blocks until `Command(resume=...)` is supplied by the TUI.
5. TUI shows a modal with the questions; on submit, the TUI client sends a `Command(resume=…)` to the loop graph.
6. `await_clarification` receives the answer, sets `state.pending_clarification_answer`, clears `state.pending_clarification`, emits `soothe.loop.clarification_answered`.
7. `route_after_clarification` reads `last_clarification_origin` and routes back to `execute`.
8. `execute` re-enters; stream wrapper sees `pending_clarification_answer`, constructs `Command(resume={origin_interrupt_id: {"answers": [...]}})`, calls `CoreAgent.astream(Command(resume=…))`, clears the answer field.
9. CoreAgent continues from where it paused.

### 5.2 Flow 2: Auto clarification (Auto mode)

Steps 1–3 identical to Flow 1.

4. `await_clarification` calls `AutoClarificationPolicy.answer(request)`, which:
   - Invokes `veritas` with the request, the first-principles slice (original user goal, intent classification, plan goal_description), and global context (workspace summary, recent step outputs, active skills/MCP).
   - Receives `VeritasAnswerSchema(answers, confidence, defer, rationale)`.
   - If `defer == True` or `confidence < auto_min_confidence`, raises `ClarificationDeferred(reason)`.
   - Otherwise returns `ClarificationAnswer(source="veritas", ...)`.
5. On success, steps 6–9 identical to Flow 1.
6. On `ClarificationDeferred`: `await_clarification` calls `ctx.mark_goal_status("awaiting_clarification", reason=…)`, emits `soothe.loop.clarification_deferred`, returns `terminate=True`. Loop stops. Goal is later resumed by `soothe goal answer <id> "..."` or autopilot scheduler when an answer arrives.

### 5.3 No plain-text fallback

Plain assistant text that asks a question is **not** detected. The relay
engages only when CoreAgent (or one of its middlewares) emits a structured
`interrupt({"type": "ask_user", ...})`. Callers that want a clarification
must use the structured form; this keeps the relay surface deterministic and
avoids false positives on assistant text that legitimately ends with a
rhetorical or summarizing question.

---

## 6. Abstract Schemas

### 6.1 `ClarificationRequest`

```
ClarificationRequest {
  questions: list[Text]
  origin_node: Enum("execute", "plan_generate", "plan_assess")
  origin_interrupt_id: ID
  loop_state_snapshot: LoopStateView   # read-only projection of LoopGraphState
}
```

### 6.2 `ClarificationAnswer`

```
ClarificationAnswer {
  answers: list[Text]                   # parallel to request.questions
  source: Enum("human", "veritas", "fallback")
  confidence: Float | Null              # auto answers only
  defer: Bool                           # signal to pause goal
  audit: Map[Text, Any]
}
```

### 6.3 `VeritasAnswerSchema`

```
VeritasAnswerSchema {
  answers: list[Text]
  confidence: Float in [0.0, 1.0]
  defer: Bool
  rationale: Text                       # short explanation for audit
}
```

### 6.4 `LoopGraphState` additions

```
LoopGraphState {
  …existing fields…
  pending_clarification: ClarificationRequest | Null
  pending_clarification_answer: ClarificationAnswer | Null
  last_clarification_origin: Enum("execute", "plan_generate", "plan_assess") | Null
}
```

### 6.5 Goal status enum addition

```
GoalStatus = Enum(
  …existing values…,
  "awaiting_clarification"               # NEW
)
```

---

## 7. Architectural Constraints

1. **Solo and autopilot share one policy abstraction.** `GoalEngine` is not introduced into the solo loop. `LoopRuntimeContext.clarification_policy` is the single injection point.
2. **Pause-on-human is checkpointable.** `InteractiveClarificationPolicy` uses LangGraph `interrupt(...)` at the loop graph level so the loop's existing checkpointer captures it. TUI restart / daemon restart resumes cleanly.
3. **Veritas never asks back.** Its system prompt forbids emitting clarifications; any clarification-shaped output is coerced to `defer=True`. No recursive clarification.
4. **Confidence floor is a safety net.** Even if veritas omits `defer`, `AutoClarificationPolicy` enforces `auto_min_confidence` and defers on low-confidence answers.
5. **Auto-approve preserved.** Action-approval interrupts (`type=="review"`) keep their current auto-approve path; this RFC does not touch them.
6. **Detection is structured-only.** Only ``ask_user`` LangGraph interrupts are detected. Plain-text questions in assistant messages are not treated as clarifications, eliminating heuristic false positives.
7. **Mode toggle is hot-swappable.** Changing Manual ↔ Auto in the TUI replaces the policy for *future* requests; in-flight requests complete under the previous policy.

---

## 8. Loop Graph Topology

### 8.1 Delta (RFC-220)

New node and edges added to `build_strange_loop_graph` (current topology defined in RFC-220 §4).

```
execute             → route_after_execute       → {record_iteration, await_clarification, END}
plan_generate       → route_after_plan          → {goal_completion, resolve_decision, await_clarification}
plan_assess         → route_after_assess        → {goal_completion, resolve_decision, plan_generate, await_clarification}
await_clarification → route_after_clarification → {execute, plan_generate, plan_assess, END}
```

`route_after_clarification` uses `state.last_clarification_origin`; `END` is only reached when policy raises `ClarificationDeferred`.

### 8.2 Routing rule

Each `route_after_*` checks `state.pending_clarification` first; if set, returns `"await_clarification"` regardless of other state. This keeps the per-node routing logic compositional and isolates the clarification short-circuit to one check.

---

## 9. Veritas Subagent

### 9.1 Role

A thin, fast subagent that answers clarifications **as the originating user would**, grounded in:

- **First-principles slice**: original user request text, intent classification, top-level `plan.goal_description`. Execution noise is excluded.
- **Global context**: workspace tree summary, last `max_context_steps` step outputs, active skills, active MCP servers, policy denials so far.

It is **not** a CoreAgent. It is a single structured-output LLM call backed by `config.create_chat_model("clarification")` (new role; defaults to the `plan_assess` model when unconfigured).

### 9.2 Module layout

```
subagents/veritas/
├── __init__.py
├── events.py           # register_event for soothe.subagent.veritas.*
├── implementation.py   # answer(request, runtime) → VeritasAnswerSchema
├── prompts.py          # system prompt enforcing no-clarification, intent voice
└── schemas.py          # VeritasAnswerSchema (Pydantic)
```

### 9.3 Wire events

| Event | Payload |
|-------|---------|
| `soothe.subagent.veritas.requested` | `question_count`, `origin_node` |
| `soothe.subagent.veritas.answered` | `confidence`, `defer`, `rationale_preview` |
| `soothe.subagent.veritas.deferred` | `reason`, `confidence` |

All registered through `register_event(...)` (RFC-600).

---

## 10. TUI Mode Toggle

| Aspect | Behavior |
|--------|----------|
| Keybind | `ctrl+m` toggles Manual ↔ Auto. Shift+Tab is retained for the loop selector. |
| Status badge | `[manual]` (green) or `[auto]` (yellow) on the persistent status line. |
| CLI flag | `soothe --mode {manual,auto}` for one-shot runs. Default: `manual` when stdin is a TTY, `auto` otherwise. |
| Autopilot | Ignores the flag. Always Auto. |
| Hot swap | Replaces `LoopRuntimeContext.clarification_policy` for future requests. In-flight requests complete under the prior policy. |
| Modal | Manual mode shows a modal with the question(s); submit sends `Command(resume=…)` to the loop graph. |

---

## 11. Events

New event types (registered via RFC-600 `register_event`):

| Event | Payload | Owner |
|-------|---------|-------|
| `soothe.loop.clarification_requested` | `questions`, `origin_node`, `mode` | `core/loop/clarification/events.py` |
| `soothe.loop.clarification_answered` | `source`, `confidence`, `defer` | same |
| `soothe.loop.clarification_deferred` | `reason`, `question_summary` | same |
| `soothe.subagent.veritas.requested` | `question_count`, `origin_node` | `subagents/veritas/events.py` |
| `soothe.subagent.veritas.answered` | `confidence`, `defer`, `rationale_preview` | same |
| `soothe.subagent.veritas.deferred` | `reason`, `confidence` | same |

---

## 12. Configuration

```yaml
agent:
  clarification:
    auto_policy: veritas              # only built-in for now
    auto_min_confidence: 0.4          # below this, treat as defer
    max_defer_age_hours: 168          # autopilot: scrub stale awaiting_clarification goals

  veritas:
    model_role: think                  # reuses existing ModelRole
    max_context_steps: 8
```

Per project rule, both `config/config.template.yml` and `config/develop/nano.yml` are updated in the same change.

---

## 13. Persistence and Out-of-Band Answers

- `awaiting_clarification` goal status is persisted by the goal-engine backend (autopilot) and by `StrangeLoopStateManager` (solo).
- New CLI: `soothe goal answer <goal_id> [--question-index N] "answer text"` writes the answer into the goal's pending-clarification record and clears `awaiting_clarification`.
- Autopilot scheduler treats `awaiting_clarification` as blocked: it does not count toward active-goal concurrency and is not selected for execution until cleared.
- TTL: goals stuck in `awaiting_clarification` longer than `max_defer_age_hours` are surfaced for operator review (autopilot only).

---

## 14. Integration Points

| External System | Integration Type | Data Exchange |
|-----------------|------------------|----------------|
| LangGraph checkpointer | API | Loop-level `interrupt(...)` snapshots loop state including pending clarification |
| TUI client | Event + Command | `clarification_requested` event → modal → `Command(resume=…)` |
| GoalEngine (autopilot) | API | `mark_goal_status("awaiting_clarification", …)`, `answer_clarification(...)` |
| `soothe` CLI | New command | `soothe goal answer <id> "..."` |
| Langfuse / observability | Events | All `clarification_*` and `veritas.*` events flow through the standard event bus |

---

## 15. Testing Strategy (informative)

Unit:
- `tests/unit/core/loop/clarification/test_protocol.py`
- `tests/unit/core/loop/clarification/test_interactive.py`
- `tests/unit/core/loop/clarification/test_auto.py`
- `tests/unit/core/loop/clarification/test_detector.py`
- `tests/unit/core/loop/orchestrator/nodes/test_await_clarification.py`
- `tests/unit/core/loop/orchestrator/test_routing.py` (extended)
- `tests/unit/subagents/veritas/test_implementation.py`
- `tests/unit/core/loop/engine/test_graph_interrupt.py` (rewritten — assert policy dispatch, not empty answers)

Integration:
- `tests/integration/core/loop/test_clarification_relay.py` — full round-trip.
- `tests/integration/core/loop/test_clarification_durable_pause.py` — checkpoint restart with pending clarification.

---

## 16. Migration & Risk

- **Behavior change**: solo CLI no longer silently empty-answers `ask_user`. Manual mode now blocks for input; Auto mode now calls veritas. This is the intended fix but a visible behavior delta.
- **Test impact**: `build_auto_resume_payload` tests rewritten. Action-approval auto-approve is preserved.
- **Veritas wrongness**: every answer emits an audit event with question + answer + source + confidence + rationale; below-threshold confidence forces defer.
- **Durability**: relies on StrangeLoop checkpointer (default-on); doctor check confirms presence.
- **Autopilot scheduler**: must recognize `awaiting_clarification` as blocked, not active — one-line change in concurrency accounting.

---

## 17. Open Items (deferred to Implementation Guide)

- Concrete shape of the structured `ask_clarification` marker / tool (vs. relying on the existing `interrupt` shape only).
- Migration of persisted goal-status enums for already-running autopilot instances.
- Whether `--mode auto` should fall back to TUI relay if `veritas` is not configured, or error out at startup.
- Exact workspace-trust interaction for veritas's filesystem summarization (RFC-621).

---

## 18. Related Documents

- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)
- [RFC-220](./RFC-220-agentic-goal-execution.md) — StrangeLoop topology that this RFC extends
- [RFC-222](./RFC-222-autopilot-mode.md) — Autopilot scheduler whose status enum gains `awaiting_clarification`
- [RFC-600](./RFC-600-plugin-extension-system.md) — `register_event` used for new event types
- [RFC-601](./RFC-601-built-in-agents.md) — Built-in subagent registry that gains `veritas`
- [RFC-403](./RFC-403-unified-event-naming.md) — Event naming for `soothe.loop.clarification_*` and `soothe.subagent.veritas.*`
- Design draft: `docs/archive/drafts/2026-06-02-clarification-relay-design.md`
- Bug trace: `trace-2626ed6b65d86c80845248e42f383bff.json`
