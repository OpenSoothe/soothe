# IG-462: Wire auto-clarification end-to-end

**RFC**: [RFC-622](../specs/RFC-622-coreagent-clarification-relay.md)
**Lineage**: [IG-460](IG-460-clarification-relay.md) introduced the relay
scaffolding (policy protocol, await_clarification node, veritas subagent, TUI
mode toggle). IG-462 turns that scaffolding into a working relay end-to-end.
**Status**: Completed 2026-06-02

---

## 1. Motivation

A trace of loop `019e886d-…-541b` showed the RFC-622 relay was completely
inert in production:

1. **Daemon never built a `ClarificationPolicy`.** `LoopRuntimeContext`
   defaulted `clarification_policy=None`; `node_execute` therefore skipped the
   detector even when the planner emitted an "Ask clarifying question…" step.
2. **TUI mode never reached the daemon.** `_clarification_mode` was tracked
   client-side only; the toggle's own docstring admitted the wire payload
   "lands later".
3. **CoreAgent never emitted `ask_user`.** Nothing in `tools/`, `middleware/`,
   or `core/agent/` raised the structured interrupt the detector was waiting
   for; the planner's prose "ask the user" steps were run as normal LLM turns
   and the loop replanned past them without asking anyone.

This guide closes all three gaps. The replay of 541b's goal now produces
`soothe.subagent.veritas.requested` → `…answered` and the planner consumes
the answer instead of generating "Propose 2-3 approaches…" cold.

---

## 2. Changes by slice

### Slice A — runtime wiring

| File | Change |
|------|--------|
| `core/loop/clarification/runtime_factory.py` (new) | `resolve_clarification_mode` (request → config fallback) + `build_clarification_policy_for_runner` (mode → `AutoClarificationPolicy` or `InteractiveClarificationPolicy`, defers chat-model construction to auto mode only). |
| `core/loop/clarification/__init__.py` | Re-export the new helpers. |
| `core/loop/engine/agent_loop.py` | `run_with_progress(... clarification_policy=...)` plumbs through into `LoopRuntimeContext`. |
| `core/runner/_runner_agentic.py` | Builds the policy per goal from per-request mode (Slice B) + config default, forwards to `AgentLoop.run_with_progress`. Errors degrade to `None` (legacy defer). |
| `core/runner/_runner_autopilot_worker.py` | Always builds the policy with `mode="auto"` — autopilot is headless. |
| `core/runner/__init__.py` (`astream`) | `clarification_mode` kwarg passes through to `_run_agentic_loop`. |
| `config/models.py` (`ClarificationConfig`) | New `default_mode: Literal["auto","manual"] = "auto"` field. |
| `config/config.template.yml` | Added `default_mode` to the documented template. (`config.dev.yml` follows the convention of omitting keys that match defaults.) |

### Slice B — wire payload plumbing

| File | Change |
|------|--------|
| `soothe-sdk/.../client/websocket.py` (`send_input`) | Accepts `clarification_mode`; appends to `payload` when set. |
| `soothe-cli/.../runtime/transport/session.py` (`send_turn`) | Pass-through kwarg. |
| `soothe-cli/.../tui/textual_adapter.py` (`execute_task_textual`) | Pass-through kwarg. |
| `soothe-cli/.../tui/app/_execution.py` | Reads `self._clarification_mode` (already tracked on the app) and attaches it on every turn. |
| `soothe-cli/.../tui/app/_messages_mixin.py` (`toggle_clarification_mode`) | Docstring updated: payload is live, not pending. |
| `soothe-daemon/.../protocol/router.py` | Normalizes `clarification_mode` ∈ `{"auto","manual"}` or `None`; added to the queue options dict. Stub `command_request` enqueue carries `clarification_mode: None`. |
| `soothe-daemon/.../_handlers.py` | Forwards to `query_engine.run_query(..., clarification_mode=…)`. |
| `soothe-daemon/.../query/engine.py` | New `clarification_mode` parameter; threaded into `LoopRunRequest`. |
| `core/protocols/runner.py` (`LoopRunRequest`) | New `clarification_mode: str \| None = None` field. |
| `soothe-daemon/.../runner/pool_runner.py`, `thread_runner.py`, `ray_actor.py` | All three subprocess paths forward `clarification_mode=req.clarification_mode` into `runner.astream`. |

### Slice C — planner-emitted `ask_user` step (option 3b)

| File | Change |
|------|--------|
| `core/loop/state/schemas.py` | `PlanGenerateStep` and `StepAction` gained `kind: Literal["action","ask_user"]` (default `"action"`) and `questions: list[str] \| None`. Validator rejects `kind="ask_user"` without `questions`. Both converters (`plan_generate_steps_to_step_actions`, `step_actions_to_plan_generate_steps`) copy the new fields by value. |
| `core/prompts/fragments/instructions/plan_generate_instructions.xml` | Added `<ASK_USER_STEP>` section telling the model when (and when not) to emit `kind="ask_user"`; documented the new `kind` / `questions` fields. |
| `core/loop/orchestrator/nodes/execute_steps.py` | Two branches. **Branch 2** (before invoking Executor): if any ready step has `kind == "ask_user"`, build a `ClarificationRequest` with `origin_interrupt_id = "planner-ask:<step_id>"`, write `pending_clarification` + `last_clarification_origin = "execute"`, return. **Branch 1** (on re-entry): when `origin_interrupt_id` starts with the planner-ask prefix, synthesize a successful `StepResult` with the answers in `outcome["answers"]` instead of building a CoreAgent resume payload. Both branches share the existing `_record_and_emit_step_completed`. |
| `core/loop/orchestrator/nodes/await_clarification.py` | Keeps `pending_clarification` alive after writing the answer — the originating node now needs to pair the two on re-entry. The originating node clears both. |
| `core/loop/orchestrator/routing.py` (`_pending_clarification`) | Treats `pending_clarification_answer` presence as the signal that we are past the relay — prevents `route_after_*` from sending the re-entry tick back into `await_clarification`. |

---

## 3. Tests

- `tests/unit/core/loop/clarification/test_runtime_factory.py` — mode resolution and policy construction.
- `tests/unit/core/loop/engine/test_agent_loop_clarification_policy.py` — `AgentLoop.run_with_progress(clarification_policy=…)` forwards into `LoopRuntimeContext`.
- `tests/unit/core/runner/test_runner_autopilot_worker.py` (extended) — autopilot forces `mode="auto"`; gracefully degrades when the builder raises.
- `tests/unit/core/loop/state/test_step_action_kind.py` — schema defaults, validator, converter round-trips.
- `tests/unit/core/loop/orchestrator/nodes/test_execute_steps_ask_user.py` — Branch 1 / Branch 2 behavior and the unchanged CoreAgent-interrupt resume path.
- `tests/unit/core/loop/orchestrator/nodes/test_await_clarification.py` (updated) — confirms the new "keep request, write answer" contract.
- `tests/integration/core/test_loop_agent_clarification_round_trip.py` — drives `AgentLoop.run_with_progress` with a stub planner that emits `kind="ask_user"` and a stub policy that returns canned answers; asserts the policy was consulted, a `step_completed` event surfaced for the ask_user step, and the loop reached `completed` without re-invoking CoreAgent for the ask.
- `tests/unit/daemon/test_message_router_loop_input.py` (extended) — `clarification_mode` normalization (case-insensitive, whitelist, blank → `None`).
- `soothe-sdk/tests/unit/client/test_websocket_send_input.py` — wire payload omits the key by default; includes it when set; coexists with other fields.

Full sweep at the end of Slice C: **2432 unit tests pass**; integration round-trip green.

---

## 4. Verification (post-implementation)

1. `./scripts/verify_finally.sh` — format/lint/unit checks.
2. End-to-end:
   - `soothe daemon restart`
   - `soothe --debug "refine code structure of soothe-daemon"`
   - Tail `~/.soothe/logs/soothe.log` grep for the loop's 4-char tag.
   - Confirm sequence: `[Plan] action=new ... next=Ask clarifying...` → `[execute] planner-emitted ask_user step …` → `s.c.l.o.n.await_clarification` → `soothe.subagent.veritas.requested` → `soothe.subagent.veritas.answered` → `step_completed (success=true)` → next iter `[Plan]` references the answer.
3. Flip badge to Manual via Shift+Tab on a fresh goal; confirm the loop pauses durably via the TUI relay.

---

## 5. Out of scope (intentional)

- A standalone `ask_user` LLM tool exposed to CoreAgent (the "3a" alternative). Re-evaluate only if agentic flows outside the planner need to clarify mid-turn.
- Heuristic plain-text question detection (the "3c" alternative). Explicitly rejected by `ClarificationDetector`'s docstring.
- Multi-question fan-out across multiple `ask_user` steps in one wave (the planner is instructed to emit at most one).
- Veritas telemetry / dashboards.
- TUI badge persistence across restarts.
