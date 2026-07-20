"""Plan-generate assess signal: inline ASSESSMENT envelope (not projected ledger)."""

from __future__ import annotations

from langchain_core.messages import SystemMessage
from soothe_nano.protocols.planner import PlanContext

from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder
from soothe.foundation.sloop.state.schemas import LoopState, StatusAssessment
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_generate_message_includes_assessment_section_when_inline() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="count files",
        assessment_status="continue",
        assessment_progress="low",
    )
    assert "ASSESSMENT:" in msg
    assert "Status: continue" in msg
    assert "Progress: low" in msg


def test_generate_message_omits_assessment_section_by_default() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(goal="count files")
    assert "ASSESSMENT:" not in msg


def test_build_plan_messages_includes_assessment_when_assess_in_ledger() -> None:
    state = LoopState(
        goal="count files",
        thread_id="t1",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="assess h", phase="plan_assess", iteration=1, thread_id="t1"),
            LoopAIMessage(
                content="{'status': 'continue', 'goal_progress': 'low'}",
                phase="plan_assess",
                iteration=1,
                thread_id="t1",
            ),
        ],
    )
    msgs = PromptBuilder().build_plan_messages(
        "count files",
        state,
        PlanContext(),
        plan_phase="generate",
        inline_assessment=StatusAssessment(
            status="continue",
            goal_progress="low",
            assessment_reasoning="I checked prior evidence.",
        ),
    )
    human = msgs[-1].content
    assert "ASSESSMENT:" in human
    assert "Status: continue" in human
    assert "Progress: low" in human
    contents = " ".join(str(getattr(m, "content", "")) for m in msgs)
    assert "assess h" not in contents


def test_build_plan_messages_includes_assessment_when_assess_skipped() -> None:
    state = LoopState(goal="count files", thread_id="t1", iteration=0)
    msgs = PromptBuilder().build_plan_messages(
        "count files",
        state,
        PlanContext(),
        plan_phase="generate",
        inline_assessment=StatusAssessment(
            status="continue",
            goal_progress="none",
            assessment_reasoning="Fresh-loop bypass: no prior execution to assess.",
        ),
    )
    human = msgs[-1].content
    assert "ASSESSMENT:" in human
    assert "Status: continue" in human
    assert "Progress: none" in human
    assert not any(
        isinstance(m, SystemMessage) and "Status:" in m.content and m is not msgs[0] for m in msgs
    )
