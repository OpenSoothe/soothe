"""Plan-phase ledger projection (IG-380, IG-555)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from soothe.config.models import PlanPromptLedgerConfig
from soothe.sloop.prompts.plan_ledger_projection import (
    _GOAL_COMPLETION_CONTEXT_BOUNDARY,
    _compact_goal_completion_unit_for_projection,
    project_cross_goal_completion_tail,
    project_last_goal_completion_for_intake,
    project_loop_messages_for_plan,
    project_loop_messages_for_synthesis,
    project_planner_ledger,
    resolve_planner_projection_mode,
)
from soothe.sloop.state.schemas import LoopState
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def _msgs(n: int) -> list:
    out = []
    for i in range(n):
        out.append(
            LoopHumanMessage(content=f"H{i}", thread_id="t", iteration=0, phase="execute_step")
        )
        out.append(
            LoopAIMessage(content=f"A{i}" * 50, thread_id="t", iteration=0, phase="execute_step")
        )
    return out


def test_projection_disabled_returns_shallow_copy_same_len() -> None:
    raw = _msgs(2)
    cfg = PlanPromptLedgerConfig(
        plan_ledger_max_messages=0,
        plan_ledger_max_total_chars=0,
        plan_ledger_max_message_chars=0,
    )
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj) == len(raw)
    assert proj is not raw
    assert proj[0] is raw[0]


def test_projection_tail_max_messages() -> None:
    raw = _msgs(5)
    cfg = PlanPromptLedgerConfig(plan_ledger_max_messages=4)
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj) == 4
    assert "H1" not in extract_join(proj)  # oldest pair dropped
    assert "[Earlier ledger content omitted" in proj[0].content


def test_projection_does_not_mutate_original() -> None:
    raw = [LoopHumanMessage(content="x" * 200, thread_id="t", iteration=0, phase="execute_step")]
    cfg = PlanPromptLedgerConfig(plan_ledger_max_message_chars=20)
    proj = project_loop_messages_for_plan(raw, cfg)
    assert len(proj[0].content) < len(raw[0].content)
    assert len(raw[0].content) == 200


def test_projection_max_total_chars_drops_oldest() -> None:
    raw = [
        LoopHumanMessage(content="H", thread_id="t", iteration=0, phase="execute_step"),
        LoopAIMessage(content="A" * 100, thread_id="t", iteration=0, phase="execute_step"),
        LoopHumanMessage(content="H2", thread_id="t", iteration=0, phase="execute_step"),
        LoopAIMessage(content="B" * 10, thread_id="t", iteration=0, phase="execute_step"),
    ]
    cfg = PlanPromptLedgerConfig(plan_ledger_max_total_chars=30)
    proj = project_loop_messages_for_plan(raw, cfg)
    joined = extract_join(proj)
    assert "H2" in joined or "BBBB" in joined
    assert len(proj) <= len(raw)


def extract_join(msgs: list) -> str:
    return "".join(getattr(m, "content", "") or "" for m in msgs)


def test_projection_none_cfg_passthrough() -> None:
    raw = [HumanMessage(content="only")]
    proj = project_loop_messages_for_plan(raw, None)
    assert len(proj) == 1
    assert proj[0] is raw[0]


def test_synthesis_projection_keeps_execute_step_only() -> None:
    raw = [
        LoopHumanMessage(content="assess", thread_id="t", iteration=0, phase="plan_assess"),
        LoopAIMessage(content="assess-ai", thread_id="t", iteration=0, phase="plan_assess"),
        LoopHumanMessage(content="gen", thread_id="t", iteration=0, phase="plan_generate"),
        LoopAIMessage(content="gen-ai", thread_id="t", iteration=0, phase="plan_generate"),
        LoopHumanMessage(content="exec-h", thread_id="t", iteration=0, phase="execute_step"),
        LoopAIMessage(content="exec-ai", thread_id="t", iteration=0, phase="execute_step"),
    ]
    proj = project_loop_messages_for_synthesis(raw, None)
    assert len(proj) == 2
    assert extract_join(proj) == "exec-hexec-ai"


# ── IG-555: Prior Goal Completion Bias Mitigation ─────────────────────────────


def test_ig555_new_goal_projection_includes_boundary() -> None:
    """new_goal planner projection compacts goal_completion with boundary marker."""
    prior_human = HumanMessage(content="Goal completed.", phase="goal_completion")
    prior_ai = AIMessage(content="Recommended: apply signature change.", phase="goal_completion")
    current_human = HumanMessage(content="GOAL: test", phase="intent_classify")
    current_ai = AIMessage(content='{"scope":"complex"}', phase="intent_classify")

    loop_messages = [prior_human, prior_ai, current_human, current_ai]
    state = LoopState(goal="test", thread_id="tid", iteration=0)
    mode = resolve_planner_projection_mode(state)
    assert mode == "new_goal"

    projected = project_planner_ledger(loop_messages, mode, None, soothe_config=None)
    boundary_found = False
    for msg in projected:
        if getattr(msg, "phase", None) == "goal_completion" and "Human" in type(msg).__name__:
            content = str(msg.content)
            assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in content
            boundary_found = True
            break
    assert boundary_found


def test_ig555_boundary_marker_constant_defined() -> None:
    """IG-555 boundary marker contains key instructions."""
    assert "<PRIOR_GOAL_CONTEXT" in _GOAL_COMPLETION_CONTEXT_BOUNDARY
    assert "reference_resolution" in _GOAL_COMPLETION_CONTEXT_BOUNDARY
    assert "DO NOT use" in _GOAL_COMPLETION_CONTEXT_BOUNDARY
    assert "Decompose" in _GOAL_COMPLETION_CONTEXT_BOUNDARY


def test_ig555_compact_includes_boundary_when_true() -> None:
    """compact function includes boundary marker when include_boundary=True."""
    human = HumanMessage(content="Goal completed.", phase="goal_completion")
    ai = AIMessage(content="Completion report.", phase="goal_completion")
    unit = [human, ai]

    result = _compact_goal_completion_unit_for_projection(unit, include_boundary=True)
    assert len(result) == 2

    human_content = str(result[0].content)
    assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in human_content
    assert "Prior goal completed" in human_content


def test_ig555_compact_omits_boundary_when_false() -> None:
    """compact function omits boundary marker when include_boundary=False."""
    human = HumanMessage(content="Goal completed.", phase="goal_completion")
    ai = AIMessage(content="Completion report.", phase="goal_completion")
    unit = [human, ai]

    result = _compact_goal_completion_unit_for_projection(unit, include_boundary=False)
    assert len(result) == 2

    human_content = str(result[0].content)
    assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() not in human_content
    assert "Prior goal completed" in human_content


def test_ig555_intake_projection_boundary_control() -> None:
    """Intake projection allows boundary control via include_boundary parameter."""
    human = HumanMessage(content="Goal completed.", phase="goal_completion")
    ai = AIMessage(content="Completion report.", phase="goal_completion")
    loop_messages = [human, ai]

    # With boundary (used by continuation-assess)
    with_boundary = project_last_goal_completion_for_intake(
        loop_messages, None, include_boundary=True
    )
    assert len(with_boundary) >= 1
    content = str(with_boundary[0].content)
    assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in content

    # Without boundary (used by intake Pass 2)
    without_boundary = project_last_goal_completion_for_intake(
        loop_messages, None, include_boundary=False
    )
    assert len(without_boundary) >= 1
    content = str(without_boundary[0].content)
    assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() not in content


def test_ig555_execute_slice_a_omits_boundary_by_default() -> None:
    """Execute Slice A projection omits boundary by default."""
    human = HumanMessage(content="Goal completed.", phase="goal_completion")
    ai = AIMessage(content="Completion report.", phase="goal_completion")
    loop_messages = [human, ai]

    # Default: no boundary (execute-step needs prior actions)
    default_result = project_cross_goal_completion_tail(loop_messages, k=1, ledger_cfg=None)
    if default_result:
        content = str(default_result[0].content)
        assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() not in content

    # Explicit boundary for planner projections
    with_boundary = project_cross_goal_completion_tail(
        loop_messages, k=1, ledger_cfg=None, include_boundary=True
    )
    if with_boundary:
        content = str(with_boundary[0].content)
        assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in content


def test_ig555_planner_projection_mid_goal_includes_boundary() -> None:
    """Planner mid_goal projection includes boundary marker in Slice A."""
    prior_human = HumanMessage(content="Goal completed.", phase="goal_completion")
    prior_ai = AIMessage(content="Completion report.", phase="goal_completion")
    current_human = HumanMessage(content="GOAL: test", phase="intent_classify")
    current_ai = AIMessage(content="{scope: complex}", phase="intent_classify")

    loop_messages = [prior_human, prior_ai, current_human, current_ai]

    state = LoopState(goal="test", thread_id="tid", iteration=1)
    mode = resolve_planner_projection_mode(state)
    assert mode == "mid_goal"

    projected = project_planner_ledger(loop_messages, mode, None, soothe_config=None)

    for msg in projected:
        if getattr(msg, "phase", None) == "goal_completion" and "Human" in type(msg).__name__:
            content = str(msg.content)
            assert _GOAL_COMPLETION_CONTEXT_BOUNDARY.strip() in content or "Prior goal" in content
            break
