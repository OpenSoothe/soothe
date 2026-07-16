"""IG-557 Phase A: assess-only projection and v2 task envelope."""

from __future__ import annotations

from types import SimpleNamespace

from soothe.foundation.context.projection import ContextBundle, PriorGoalSummary
from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_planner_ledger,
    project_planner_ledger_for_assess,
)
from soothe.foundation.sloop.prompts.user_message import UserMessageBuilder
from soothe.foundation.sloop.state.schemas import (
    AgentDecision,
    LoopState,
    StepAction,
    StepResult,
)
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import PlanContext


def test_assess_execute_ai_compaction_keeps_head_and_tail() -> None:
    """Oversized execute AI must keep deliverable head + closing tail (not tail-only)."""
    from soothe.config.models import PlanAssessPromptConfig
    from soothe.foundation.sloop.prompts.plan_ledger_projection import (
        _compact_execute_ai_for_assess,
    )

    head = (
        "## Deliverable: File Counts by Extension\n"
        "| Extension | Count |\n"
        "| `.py` | 1786 |\n"
        "| `.md` | 962 |\n"
    )
    middle = ("PADDING_ONLY " * 200) + "\n"
    tail = "Client surface is polyglot: TypeScript + Go.\nStep IUM-02 complete.\n"
    full = head + middle + tail
    assert len(full) > 400

    msg = LoopAIMessage(content=full, phase="execute_step", thread_id="t", step_id="IUM-02")
    compacted = _compact_execute_ai_for_assess(msg, 400)
    text = str(compacted.content)
    assert "1786" in text
    assert "TypeScript" in text or "IUM-02 complete" in text
    assert "abbr" in text  # middle omitted via preview marker
    # Tail-only compaction would drop the table; head+tail must retain both ends.
    assert "`.py`" in text or "Extension" in text

    cfg = SimpleNamespace(
        agent=SimpleNamespace(
            loop=SimpleNamespace(
                plan_assess_prompt=PlanAssessPromptConfig(execute_ai_max_chars=400),
            )
        )
    )
    projected = project_planner_ledger_for_assess(
        [msg],
        "mid_goal",
        None,
        soothe_config=cfg,
    )
    joined = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert "1786" in joined
    assert "TypeScript" in joined or "IUM-02 complete" in joined


def test_assess_projection_excludes_plan_phases_and_slice_a() -> None:
    ledger = [
        LoopHumanMessage(content="gc h", phase="goal_completion", thread_id="t"),
        LoopAIMessage(
            content="gc a completed successfully",
            phase="goal_completion",
            thread_id="t",
        ),
        LoopHumanMessage(content="intent h", phase="intent_classify", thread_id="t"),
        LoopAIMessage(content='{"intake":"complex"}', phase="intent_classify", thread_id="t"),
        LoopHumanMessage(content="gen h", phase="plan_generate", thread_id="t"),
        LoopAIMessage(content='{"steps":[]}', phase="plan_generate", thread_id="t"),
        LoopHumanMessage(content="assess h", phase="plan_assess", thread_id="t"),
        LoopAIMessage(content="assess a", phase="plan_assess", thread_id="t"),
        LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
        LoopAIMessage(content="exec outcome ok", phase="execute_step", thread_id="t"),
    ]
    projected = project_planner_ledger_for_assess(ledger, "mid_goal", None)
    contents = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert "gc a" not in contents
    assert "intent" not in contents
    assert "gen h" not in contents
    assert "assess" not in contents
    assert "exec h" not in contents
    assert "exec outcome ok" in contents
    assert all(getattr(m, "phase", None) == "execute_step" for m in projected)
    assert all(type(m).__name__.endswith("AIMessage") for m in projected)


def test_generate_projection_unchanged_includes_slice_a_and_plan() -> None:
    ledger = [
        LoopHumanMessage(content="gc h", phase="goal_completion", thread_id="t"),
        LoopAIMessage(content="gc a1", phase="goal_completion", thread_id="t"),
        LoopHumanMessage(content="gen h", phase="plan_generate", thread_id="t"),
        LoopAIMessage(content="gen a", phase="plan_generate", thread_id="t"),
        LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
        LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
    ]
    projected = project_planner_ledger(ledger, "mid_goal", None)
    contents = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert "gc a1" in contents
    assert "gen h" in contents
    assert "exec h" in contents


def test_assess_envelope_single_full_goal_denylist_sections() -> None:
    bundle = ContextBundle(
        prior_goals=[
            PriorGoalSummary(
                goal_id="g0",
                description="prior goal",
                status="completed",
                step_summary="",
                completion_text="done",
            )
        ],
        goal_lineage="parent → child",
        step_lineage="step reasoning history",
        goal_progress="2/5 completed",
    )
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(
        goal="full goal text that must not be truncated at one hundred twenty chars " * 2,
        dag_context=SimpleNamespace(
            has_prior_state=True,
            total_steps=5,
            completed_steps=2,
            failed_step_ids=[],
            ready_step_ids=["03"],
            pending_step_ids=["04", "05"],
            chain_depth=2,
            success_rate=1.0,
            replan_count=0,
        ),
        skill_context="skill body",
        context_bundle=bundle,
        projection_mode="mid_goal",
    )
    assert msg.count("GOAL:") == 1
    assert "full goal text that must not be truncated" in msg
    assert "PRIOR GOALS:" not in msg
    assert "GOAL LINEAGE:" not in msg
    assert "STEP LINEAGE:" not in msg
    assert "DAG STATUS:" not in msg
    assert "SKILL REFERENCE:" not in msg
    assert "TASK:" in msg


def test_build_plan_messages_assess_uses_execute_ai_only_ledger() -> None:
    state = LoopState(
        goal="multi part goal",
        thread_id="t",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="gc h", phase="goal_completion", thread_id="t"),
            LoopAIMessage(content="gc done", phase="goal_completion", thread_id="t"),
            LoopHumanMessage(content="gen h", phase="plan_generate", thread_id="t"),
            LoopAIMessage(content="gen a", phase="plan_generate", thread_id="t"),
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="wave evidence", phase="execute_step", thread_id="t"),
        ],
    )
    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="assess",
    )
    ledger_text = "\n".join(str(getattr(m, "content", "")) for m in msgs[1:-1])
    assert "gc done" not in ledger_text
    assert "gen h" not in ledger_text
    assert "exec h" not in ledger_text
    assert "wave evidence" in ledger_text
    human = msgs[-1].content
    assert human.count("GOAL:") == 1
    assert "PRIOR GOALS:" not in human


def test_plan_coverage_present_when_decision_has_steps() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        iteration=1,
        current_decision=AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="01", description="a", action="noop"),
                StepAction(id="02", description="b", action="noop"),
            ],
        ),
    )
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="assess",
    )
    human = msgs[-1].content
    assert "PLAN COVERAGE:" in human
    assert "completed_steps: 1/2" in human
    assert "remaining_step_ids: 02" in human
