"""Regression tests for plan-mode approve → FINALIZE scratch effects (Bug #4).

``handle_plan_mode_review_answer`` routes approve → FINALIZE, and
``node_goal_completion`` requires ``ctx.scratch.plan_result`` (it fatally
errors with "Goal completion reached without plan result" when it is None).
The plan-mode path skips DISPATCH, so the branches that normally set
``plan_result`` never ran. These tests pin the contract that approve leaves a
terminal ``PlanResult`` and the follow-on exec signal on scratch so finalize
proceeds and enqueues the exec goal.
"""

from __future__ import annotations

import types

from soothe.sloop.plans.plan_mode_review import handle_plan_mode_review_answer
from soothe.sloop.relay.relay import LoopRelay


def _build_ctx(
    plan_path: str = "/ws/.soothe/plans/p.md", plan_markdown: str = "# Plan\n\nDo it."
) -> types.SimpleNamespace:
    scratch = types.SimpleNamespace(
        plan_draft_path=plan_path,
        plan_draft_markdown=plan_markdown,
        plan_review_comments=None,
        follow_on_exec=None,
        plan_result=None,
        plan_rejected=False,
        decompose_proposals=[],
        decision=None,
    )
    loop_state = types.SimpleNamespace(
        goal="count one to five",
        thread_id="t1",
        iteration=0,
        workspace="/ws",
    )
    ctx = types.SimpleNamespace(scratch=scratch, loop_state=loop_state, ce=None)

    async def _emit(name, payload):
        pass

    ctx.relay = LoopRelay(loop_id="test", emit=_emit)
    return ctx


def _approve_answer_state() -> dict:
    return {
        "source": "human",
        "answers": ["Approve", ""],
        "defer": False,
        "audit": {},
    }


def _reject_answer_state() -> dict:
    return {
        "source": "human",
        "answers": ["Reject", ""],
        "defer": False,
        "audit": {},
    }


def _state(answer_state: dict, *, scratch: dict | None = None) -> dict:
    relay_state: dict = {"answer": answer_state, "inbox": [], "active_origin": "plan_mode_review"}
    if scratch is not None:
        relay_state["scratch"] = scratch
    return {"relay_state": relay_state}


def test_approve_sets_terminal_plan_result_on_scratch() -> None:
    """Bug #4: approve must populate ctx.scratch.plan_result so finalize does not fatal."""
    ctx = _build_ctx()
    state = _state(
        _approve_answer_state(),
        scratch={
            "plan_draft_path": ctx.scratch.plan_draft_path,
            "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
        },
    )
    out = handle_plan_mode_review_answer(ctx, state)

    assert out["plan_approved_follow_on"] is True
    pr = ctx.scratch.plan_result
    assert pr is not None, "approve must set ctx.scratch.plan_result for node_goal_completion"
    assert pr.status == "done"
    assert pr.require_goal_completion is False  # ledger_direct: no synthesis call
    assert (pr.full_output or "").strip()  # plan body carried as the goal answer


def test_approve_stashes_follow_on_exec_signal() -> None:
    """approve stashes goal_prompt + plan_path for the daemon to enqueue the exec goal."""
    ctx = _build_ctx()
    out = handle_plan_mode_review_answer(ctx, _state(_approve_answer_state()))

    assert out["plan_approved_follow_on"] is True
    sig = ctx.scratch.follow_on_exec
    assert sig is not None
    assert sig["plan_path"] == ctx.scratch.plan_draft_path
    assert sig["goal_prompt"]  # resolved from loop_state.goal


def test_approve_clears_clarification_channels() -> None:
    """approve must clear relay_state so routers route → FINALIZE, not AWAIT_USER."""
    ctx = _build_ctx()
    out = handle_plan_mode_review_answer(ctx, _state(_approve_answer_state()))

    assert out["relay_state"]["answer"] is None
    assert out["relay_state"]["inbox"] == []


def test_reject_terminates_without_follow_on_exec() -> None:
    """Reject finalizes the current goal and does not execute the plan."""
    ctx = _build_ctx()
    out = handle_plan_mode_review_answer(ctx, _state(_reject_answer_state()))

    assert out["plan_rejected_terminal"] is True
    assert out["relay_state"]["answer"] is None
    assert ctx.scratch.follow_on_exec is None


def test_reject_leaves_no_plan_result_to_report() -> None:
    """Reject must not build a terminal PlanResult — there is nothing to summarize."""
    ctx = _build_ctx()
    handle_plan_mode_review_answer(ctx, _state(_reject_answer_state()))

    assert ctx.scratch.plan_rejected is True
    assert ctx.scratch.plan_result is None


def test_reject_records_no_goal_completion_ledger_entry() -> None:
    """Reject writes no ledger message: no plan completion, no goal completion."""
    from unittest.mock import patch

    from soothe.sloop.plans import plan_mode_review

    ctx = _build_ctx()
    with (
        patch.object(plan_mode_review, "_record_plan_action_ledger") as action_ledger,
        patch.object(plan_mode_review, "_record_plan_completion_ledger") as completion_ledger,
    ):
        plan_mode_review.handle_plan_mode_review_answer(ctx, _state(_reject_answer_state()))

    action_ledger.assert_not_called()
    completion_ledger.assert_not_called()
