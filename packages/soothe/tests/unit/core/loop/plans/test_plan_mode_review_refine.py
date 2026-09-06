"""Regression tests for plan-mode Refine → refinement re-synthesis.

When the operator requests plan refinement,
``handle_plan_mode_review_answer`` stores the comments on
``ctx.scratch.plan_review_comments`` and flags ``plan_refinement_requested``.
``node_plan_review`` (async) then calls ``synthesize_plan`` with the comments +
prior plan, overwrites the draft, clears the comments, and re-emits the
review. This closes the refinement loop that was previously broken: the
comments were stored but never consumed, so the user kept seeing the same plan.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, patch

from soothe.sloop.plans import plan_mode_review
from soothe.sloop.plans.plan_synthesizer import _build_refinement_trigger
from soothe.sloop.relay.relay import LoopRelay


def _build_ctx(
    plan_path: str = "/ws/.soothe/plans/p.md",
    plan_markdown: str = "# Plan\n\nDo it.",
) -> types.SimpleNamespace:
    scratch = types.SimpleNamespace(
        plan_draft_path=plan_path,
        plan_draft_markdown=plan_markdown,
        plan_review_comments=None,
        follow_on_exec=None,
        plan_result=None,
        decompose_proposals=[],
        decision=None,
    )
    loop_state = types.SimpleNamespace(
        goal="count one to five",
        thread_id="t1",
        iteration=0,
        workspace="/ws",
    )
    strange_loop = types.SimpleNamespace(
        config=None,
        goal_synthesis_model=lambda: None,
        _fast_llm=None,
    )
    ctx = types.SimpleNamespace(
        scratch=scratch, loop_state=loop_state, ce=None, strange_loop=strange_loop
    )
    ctx.emit = AsyncMock()

    async def _emit(name, payload):
        await ctx.emit(name, payload)

    ctx.relay = LoopRelay(loop_id="test", emit=_emit)
    return ctx


def _refine_answer_state(comments: str) -> dict:
    return {
        "source": "human",
        "answers": ["Refine", comments],
        "defer": False,
        "audit": {},
    }


def _answer_state_dict(comments: str) -> dict:
    """relay_state with a refine answer slot set."""
    return {
        "relay_state": {
            "answer": _refine_answer_state(comments),
            "inbox": [],
            "active_origin": "plan_mode_review",
        }
    }


def _pending_with_plan(ctx) -> dict:
    """relay_state carrying the plan body in the scratch projection."""
    return {
        "relay_state": {
            "inbox": [],
            "active_origin": "plan_mode_review",
            "answer": _refine_answer_state(""),
            "scratch": {
                "plan_draft_path": ctx.scratch.plan_draft_path,
                "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
            },
        }
    }


def test_refine_with_comments_sets_refinement_flag() -> None:
    """Refine with comments flags ``plan_refinement_requested`` for the node."""
    ctx = _build_ctx()
    state = {
        "relay_state": {
            "answer": _refine_answer_state("reuse deepagents tokens"),
            "inbox": [],
            "active_origin": "plan_mode_review",
            "scratch": {
                "plan_draft_path": ctx.scratch.plan_draft_path,
                "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
            },
        }
    }
    out = plan_mode_review.handle_plan_mode_review_answer(ctx, state)

    assert out["plan_refinement_requested"] is True
    assert ctx.scratch.plan_review_comments == "reuse deepagents tokens"


def test_refine_without_comments_does_not_flag_refinement() -> None:
    """Refine with no comments re-emits the same plan."""
    ctx = _build_ctx()
    state = {
        "relay_state": {
            "answer": _refine_answer_state(""),
            "inbox": [],
            "active_origin": "plan_mode_review",
            "scratch": {
                "plan_draft_path": ctx.scratch.plan_draft_path,
                "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
            },
        }
    }
    out = plan_mode_review.handle_plan_mode_review_answer(ctx, state)

    assert "plan_refinement_requested" not in out
    assert ctx.scratch.plan_review_comments == ""


def test_node_plan_review_refines_on_refine_resume() -> None:
    """node_plan_review re-synthesizes the plan after a reject-with-comments.

    The async node calls ``synthesize_plan`` with ``refinement_comments`` +
    ``prior_plan``, overwrites the draft, clears the comments, and re-emits
    the pending clarification carrying the revised plan.
    """
    ctx = _build_ctx(plan_markdown="# Plan\n\nOriginal plan.")
    ctx.scratch.plan_review_comments = "reuse deepagents tokens"
    state = {
        "relay_state": {
            "answer": _refine_answer_state("reuse deepagents tokens"),
            "inbox": [],
            "active_origin": "plan_mode_review",
            "scratch": {
                "plan_draft_path": ctx.scratch.plan_draft_path,
                "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
            },
        }
    }

    # ``handle_plan_mode_review_answer`` already ran (simulated by setting the
    # flag + comments on scratch). Patch the sync handle to return the flagged
    # output, and patch ``synthesize_plan`` + ``save_plan_draft`` + the ledger
    # recorder so the test stays unit-level.
    handle_out = plan_mode_review.build_plan_mode_review_pending(ctx)
    handle_out["plan_refinement_requested"] = True

    revised_plan = "## Plan: Revised\n\nReuse deepagents token estimation."

    def fake_save_draft(_ctx, report):
        _ctx.scratch.plan_draft_markdown = report
        _ctx.scratch.plan_draft_path = "/ws/.soothe/plans/revised.md"
        return "/ws/.soothe/plans/revised.md"

    with (
        patch.object(
            plan_mode_review, "handle_plan_mode_review_answer", return_value=handle_out
        ) as mock_handle,
        patch.object(
            plan_mode_review,
            "_refine_plan",
            new=AsyncMock(return_value=revised_plan),
        ) as mock_refine,
        patch.object(plan_mode_review, "save_plan_draft", side_effect=fake_save_draft) as mock_save,
        patch.object(plan_mode_review, "_record_plan_completion_ledger") as mock_ledger,
    ):
        result = asyncio.run(plan_mode_review.node_plan_review(ctx, state))

    # ``_refine_plan`` was called with the ctx carrying the comments.
    mock_refine.assert_awaited_once()
    _args = mock_refine.call_args.args
    assert _args[0] is ctx

    # Draft was overwritten with the revised plan.
    mock_save.assert_called_once()
    _args = mock_save.call_args.args
    assert _args[1] == revised_plan  # (ctx, report)
    assert ctx.scratch.plan_draft_markdown == revised_plan

    # Comments were consumed (cleared) so a subsequent approve is clean.
    assert ctx.scratch.plan_review_comments is None

    # The returned pending carries the revised plan markdown.
    assert (
        "revised"
        in str(result["relay_state"].get("scratch", {}).get("plan_draft_markdown", "")).lower()
    )
    mock_ledger.assert_called_once_with(ctx, revised_plan)
    mock_handle.assert_called_once_with(ctx, state)


def test_node_plan_review_keeps_old_draft_when_refinement_fails() -> None:
    """When refinement synthesis returns empty, the prior draft is kept."""
    ctx = _build_ctx(plan_markdown="# Plan\n\nOriginal plan.")
    ctx.scratch.plan_review_comments = "reuse deepagents tokens"
    state = {
        "relay_state": {
            "answer": _refine_answer_state("reuse deepagents tokens"),
            "inbox": [],
            "active_origin": "plan_mode_review",
            "scratch": {
                "plan_draft_path": ctx.scratch.plan_draft_path,
                "plan_draft_markdown": ctx.scratch.plan_draft_markdown,
            },
        }
    }

    handle_out = plan_mode_review.build_plan_mode_review_pending(ctx)
    handle_out["plan_refinement_requested"] = True

    with (
        patch.object(plan_mode_review, "handle_plan_mode_review_answer", return_value=handle_out),
        patch.object(
            plan_mode_review,
            "synthesize_plan",
            new=AsyncMock(return_value=""),
        ),
        patch.object(plan_mode_review, "save_plan_draft") as mock_save,
        patch.object(plan_mode_review, "_record_plan_completion_ledger") as mock_ledger,
    ):
        result = asyncio.run(plan_mode_review.node_plan_review(ctx, state))

    # Synthesis failed → draft NOT overwritten, no new ledger pair.
    mock_save.assert_not_called()
    mock_ledger.assert_not_called()
    assert ctx.scratch.plan_draft_markdown == "# Plan\n\nOriginal plan."
    # Comments were still consumed to avoid a retry loop.
    assert ctx.scratch.plan_review_comments is None
    # The original handle_out (carrying the old draft) is returned as-is.
    assert result is handle_out


def test_build_refinement_trigger_includes_comments_and_prior_plan() -> None:
    """The refinement trigger message carries the feedback + prior plan."""
    msg = _build_refinement_trigger("reuse deepagents tokens", "# Plan\n\nOriginal.")
    assert "reuse deepagents tokens" in msg
    assert "# Plan\n\nOriginal." in msg
    assert "requested" in msg
    assert "Refinement feedback" in msg
    assert "Previous plan draft" in msg


def test_build_refinement_trigger_truncates_large_prior_plan() -> None:
    """A very large prior plan is truncated to protect the input budget."""
    huge = "x" * 20_000
    msg = _build_refinement_trigger("fix it", huge)
    assert "[truncated]" in msg
    assert len(msg) < 20_000


# ---------------------------------------------------------------------------
# plan_review_comments persistence across worker restart
# ---------------------------------------------------------------------------


def test_build_plan_mode_review_pending_persists_comments() -> None:
    """build_plan_mode_review_pending stores plan_review_comments in the pending dict."""
    ctx = _build_ctx(plan_markdown="# Plan\n\nDraft plan.")
    ctx.scratch.plan_review_comments = "reuse deepagents tokens"
    pending = plan_mode_review.build_plan_mode_review_pending(ctx)
    assert pending["relay_state"]["scratch"]["plan_review_comments"] == "reuse deepagents tokens"


def test_hydrate_scratch_restores_comments_from_pending() -> None:
    """hydrate_scratch_from_pending restores plan_review_comments from the pending channel."""
    ctx = _build_ctx(plan_markdown="# Plan\n\nDraft.")
    state = {
        "relay_state": {
            "inbox": [],
            "answer": None,
            "scratch": {
                "plan_draft_path": "/ws/.soothe/plans/p.md",
                "plan_draft_markdown": "# Plan\n\nDraft.",
                "plan_review_comments": "fix the token counting",
            },
        }
    }
    plan_mode_review.hydrate_scratch_from_pending(ctx, state)
    assert ctx.scratch.plan_review_comments == "fix the token counting"


def test_hydrate_scratch_does_not_overwrite_existing_comments() -> None:
    """hydrate_scratch_from_pending does not clobber comments already on scratch."""
    ctx = _build_ctx()
    ctx.scratch.plan_review_comments = "already here"
    state = {
        "relay_state": {
            "inbox": [],
            "answer": None,
            "scratch": {
                "plan_review_comments": "from channel",
            },
        }
    }
    plan_mode_review.hydrate_scratch_from_pending(ctx, state)
    assert ctx.scratch.plan_review_comments == "already here"
