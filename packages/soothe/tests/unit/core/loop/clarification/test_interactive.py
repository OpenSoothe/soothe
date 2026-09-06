"""Unit tests for InteractiveClarificationPolicy."""

from __future__ import annotations

from typing import Any

from soothe.config.models import ToolApprovalConfig
from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.clarification.tool_approval_pipeline import ToolApprovalPipeline


def _request(num_questions: int = 1, *, origin_node: str = "execute") -> ClarificationRequest:
    return ClarificationRequest(
        questions=tuple(f"q{i}" for i in range(num_questions)),
        origin_node=origin_node,  # type: ignore[arg-type]
        origin_interrupt_id="i1",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="",
            user_request="",
            iteration=0,
            intent_classification=None,
            plan_summary=None,
            recent_step_outputs=(),
            workspace_summary=None,
            active_skills=(),
            active_mcp_servers=(),
        ),
    )


def _tool_approval_request(command: str) -> ClarificationRequest:
    return ClarificationRequest(
        questions=("Approve run_command?",),
        origin_node="tool_approval",  # type: ignore[arg-type]
        origin_interrupt_id="iTA",
        loop_state=LoopStateView(
            goal_id="g",
            goal_description="",
            user_request="",
            iteration=0,
            intent_classification=None,
            plan_summary=None,
            recent_step_outputs=(),
            workspace_summary=None,
            active_skills=(),
            active_mcp_servers=(),
        ),
        metadata={"action_requests": [{"name": "run_command", "args": {"command": command}}]},
    )


def _pipeline() -> ToolApprovalPipeline:
    return ToolApprovalPipeline(ToolApprovalConfig())


class _EmitCollector:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


# ── Manual park (no pipeline) ────────────────────────────────────────────


async def test_answer_returns_manual_defer() -> None:
    """Without a pipeline, answer() returns defer=True with defer_kind='manual'."""
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_request())
    assert ans.defer is True
    assert ans.source == "human"
    assert ans.audit.get("defer_kind") == "manual"


async def test_answer_does_not_reemit_clarification_requested() -> None:
    """answer() (not fallback) must not emit — await_clarification already did."""
    emit = _EmitCollector()
    policy = InteractiveClarificationPolicy(emit=emit)
    await policy.answer(_request())
    assert emit.events == []


async def test_answer_as_manual_fallback_emits_mode_manual() -> None:
    """answer_as_manual_fallback re-announces with mode=manual before deferring."""
    emit = _EmitCollector()
    policy = InteractiveClarificationPolicy(emit=emit)
    ans = await policy.answer_as_manual_fallback(_request())
    assert ans.defer is True
    assert ans.audit.get("defer_kind") == "manual"
    assert len(emit.events) == 1
    assert emit.events[0][0] == "clarification_requested"
    assert emit.events[0][1]["mode"] == "manual"


# ── Pre-filter (tool_approval pipeline) ──────────────────────────────────


async def test_pre_filter_deny_rule_auto_rejects_without_asking() -> None:
    policy = InteractiveClarificationPolicy(tool_approval_pipeline=_pipeline())
    ans = await policy.answer(_tool_approval_request("su root"))
    assert ans.source == "static"
    assert ans.answers == ("reject",)
    assert ans.defer is False


async def test_pre_filter_asks_human_for_allow_rule_match_by_default() -> None:
    policy = InteractiveClarificationPolicy(tool_approval_pipeline=_pipeline())
    ans = await policy.answer(_tool_approval_request("echo hello"))
    # No allow rule match → falls through to the human (defer).
    assert ans.defer is True
    assert ans.audit.get("defer_kind") == "manual"


async def test_pre_filter_default_approves_when_enabled() -> None:
    policy = InteractiveClarificationPolicy(
        tool_approval_pipeline=_pipeline(), manual_allow_rules=True
    )
    ans = await policy.answer(_tool_approval_request("echo hello"))
    assert ans.source == "static"
    assert ans.answers == ("approve",)


async def test_pre_filter_asks_human_when_allow_rules_disabled() -> None:
    policy = InteractiveClarificationPolicy(
        tool_approval_pipeline=_pipeline(), manual_allow_rules=False
    )
    ans = await policy.answer(_tool_approval_request("echo hello"))
    assert ans.defer is True


async def test_pre_filter_skipped_without_pipeline() -> None:
    policy = InteractiveClarificationPolicy()
    ans = await policy.answer(_tool_approval_request("echo hello"))
    assert ans.defer is True
    assert ans.audit.get("defer_kind") == "manual"


async def test_manual_fallback_path_skips_pre_filter() -> None:
    """answer_as_manual_fallback does NOT run the pipeline pre-filter."""
    emit = _EmitCollector()
    policy = InteractiveClarificationPolicy(emit=emit, tool_approval_pipeline=_pipeline())
    ans = await policy.answer_as_manual_fallback(_tool_approval_request("sudo rm -rf /"))
    # Should defer (manual), NOT auto-reject — the pipeline is skipped.
    assert ans.defer is True
    assert ans.audit.get("defer_kind") == "manual"


async def test_bind_emit_wires_callback() -> None:
    emit = _EmitCollector()
    policy = InteractiveClarificationPolicy()
    policy.bind_emit(emit)
    await policy.answer_as_manual_fallback(_request())
    assert len(emit.events) == 1
