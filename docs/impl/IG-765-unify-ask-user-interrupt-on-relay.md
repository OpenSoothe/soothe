# IG-765: Unify ask_user and interrupt_on (tool_approval) Relay Paths

**Created**: 2026-08-26
**Status**: Implemented (verification blocked: `soothe` imports `soothe_nano.utils.llm.invoke_policy` at package init, but the resolved `soothe-nano` (1.2.11, PyPI/editable) lacks it — a `soothe-nano` release gap, not an IG-765 issue. Correct fix per project policy: release a new `soothe-nano`, then bump `soothe`'s `soothe-nano` dep. Local uv.lock bump was attempted and reverted; no committed dep changes.)
**Related**: RFC-622 (clarification relay), RFC-904 (sloop recursive decomposition),
IG-763 (ask_user in-thread continuation)

## Problem

`ask_user` (RFC-622) and `interrupt_on`/`tool_approval` (deepagents
`HumanInTheLoopMiddleware`) are two distinct clarification origins that share
the *entire* relay spine — detection from a `GraphInterrupt`, capture into
`ClarificationCapture`, serialization into `pending_clarification`,
`await_clarification` → `ClarificationPolicy.answer()`, `Command(resume=...)`
on the interrupted thread, history append.

Despite that shared spine, the *divergence* is duplicated across two files:

1. **Detection** — `Executor._capture_interrupts` (`executor.py:254`) branches
   on two separate `is_*` predicates and two `detector.from_*` methods.
2. **Resume construction** — `node_execute` (`execute.py:392`) branches on
   `origin_node == ORIGIN_TOOL_APPROVAL` to emit a `decisions` payload versus
   an `answers` payload, and `_answer_to_decision` (plus its token frozensets)
   lives in `execute.py` only to serve that branch.

The two branches encode the same "which origin → which resume shape" decision
in two places. Adding a third origin would mean editing both. This is the kind
of parallel branching that drifts.

## Goal

Collapse the duplicated branching without merging the two origins. They are
semantically different — `ask_user` is an open question/decision gate
(force-manual, free-text answers); `tool_approval` is a concrete tool-action
gate (auto-eligible via veritas security-approver, approve/reject/edit
decisions). The different resume payload shape and auto-mode eligibility come
from that distinction, not from accident. Keep both origins; centralize each
origin's logic in exactly one place.

## Design

### 1. Single detection entry point (`clarification/detector.py`)

Add `ClarificationDetector.detect(value, *, interrupt_id, loop_state,
origin_node=ORIGIN_EXECUTE)` that routes by payload key:

- `"action_requests" in value` → `_from_tool_approval_interrupt` (origin
  forced to `ORIGIN_TOOL_APPROVAL`).
- `value.get("type") == "ask_user"` → `_from_ask_user` (origin from caller).
- else → `None`.

`from_interrupt` / `from_tool_approval_interrupt` remain as public delegating
methods (they are exercised by existing detector tests) so no test churn is
required for the granular constructors. The executor's `if/elif is_*` block
becomes one `detector.detect(...)`.

### 2. Origin-aware resume builder (`engine/execute/graph_interrupt.py`)

Move `_answer_to_decision` and its token frozensets out of `execute.py` into
`graph_interrupt.py` (which already owns `build_tool_approval_resume_payload`),
and add:

```python
def build_clarification_resume_payload(request, answer) -> dict[str, Any]:
    if request.origin_node == ORIGIN_TOOL_APPROVAL:
        decision = _answer_to_decision(answer.answers[0] if answer.answers else "approve")
        return build_tool_approval_resume_payload(
            request.origin_interrupt_id, decisions=[{"type": decision}])
    return {request.origin_interrupt_id: {"answers": list(answer.answers)}}
```

`node_execute` (`execute.py:392`) replaces the `tool_approval` vs `ask_user`
`elif` with `resume_answer_payload = build_clarification_resume_payload(req, ans)`.
The ask_user-only side effect `_append_ask_user_loop_messages` stays in
`execute.py` but is gated on `origin_node != ORIGIN_TOOL_APPROVAL`.

### What stays separate (correctly)

- **Origins** — `execute` vs `tool_approval`; still drive TUI rendering (input
  box vs approve/reject selector) and auto-mode (`requires_manual` /
  `force_manual_origins`), both keyed off `origin_node`.
- **Planner-emitted `ask_user`** Branch 1 (`execute.py:381`,
  `PLANNER_ASK_INTERRUPT_PREFIX`) — unrelated to this pair (no live interrupt
  to resume); out of scope.
- `ClarificationCapture`, `await_clarification`, policy dispatch, history — already unified; untouched.

## Files

- `packages/soothe/src/soothe/sloop/clarification/detector.py` — add `detect()`.
- `packages/soothe/src/soothe/sloop/engine/execute/graph_interrupt.py` — add
  `build_clarification_resume_payload`; move `_answer_to_decision` + tokens.
- `packages/soothe/src/soothe/sloop/engine/execute/executor.py` — use `detect()`.
- `packages/soothe/src/soothe/sloop/stations/execute/execute.py` — use
  `build_clarification_resume_payload`; drop `_answer_to_decision`/tokens.
- Tests: repoint `_answer_to_decision` imports to `graph_interrupt`; add a
  `build_clarification_resume_payload` test in `test_tool_approval_bridge.py`.

## Verification

`./scripts/verify_finally.sh` — zero lint, all tests green. The existing
`test_ask_user_and_interrupt_on_e2e.py` exercises both origins end-to-end and
must still pass unchanged.
