"""Intake station Langfuse invoke config + graph node inheritance."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.config import SootheConfig
from soothe.sloop.intention import IntentClassification
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.stations.preprocess.intake import node_intent_classify
from soothe.utils.observability.langfuse import GoalLoopTrace


def _goal_trace(*, enabled: bool = True, trace_id: str | None = "trace-goal-1") -> GoalLoopTrace:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = enabled
    cfg.observability.langfuse.trace_name = "soothe-dev"
    return GoalLoopTrace(
        soothe_config=cfg,
        trace_id=trace_id,
        session_id="thread-1",
        loop_id="loop-1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )


def test_intake_invoke_config_pins_trace_id() -> None:
    pytest.importorskip("langfuse")

    out = _goal_trace().intake_invoke_config(
        purpose="classify_intake",
        component="classifier.intake.classify",
        phase="intake_classify",
    )
    handler = out["callbacks"][0]
    assert handler.trace_context == {"trace_id": "trace-goal-1"}
    assert out["run_name"] == "soothe-dev:intake-classify"
    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"


def test_intake_invoke_config_inherits_graph_handler() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    graph_handler = SootheLangfuseCallbackHandler(trace_context={"trace_id": "trace-goal-1"})
    out = _goal_trace().intake_invoke_config(
        purpose="classify_intake",
        component="classifier.intake.classify",
        phase="intake_classify",
        inherit_callbacks_from={"callbacks": [graph_handler]},
    )

    # Flatten inherited handlers onto a list so nano structured-output never
    # sees LangGraph's AsyncCallbackManager via ensure_config / merge_configs.
    assert out["callbacks"] == [graph_handler]
    assert out["run_name"] == "soothe-dev:intake-classify"


def test_pinned_llm_invoke_config_uses_explicit_run_name() -> None:
    """Execute auxiliaries must not inherit the ``intake`` run-name fallback."""
    pytest.importorskip("langfuse")

    out = _goal_trace().pinned_llm_invoke_config(
        purpose="assess_step_deliverable",
        component="executor.step_deliverable",
        phase="execute_step",
        run_name="soothe-dev:execute-step",
    )
    assert out["run_name"] == "soothe-dev:execute-step"
    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"
    assert out["callbacks"][0].trace_context == {"trace_id": "trace-goal-1"}


@pytest.mark.asyncio
async def test_graph_intake_node_inherits_graph_runnable_config() -> None:
    """Graph-entry classification reuses the graph callback hierarchy."""
    classifier = MagicMock()
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        reasoning="Lightweight change.",
        task_complexity=TaskComplexity.SIMPLE,
    )
    classifier.classify_intake = AsyncMock(return_value=intent)

    ce = MagicMock()
    ce.get_ledger_entries.return_value = []

    ctx = SimpleNamespace(
        loop_state=SimpleNamespace(
            goal="Fix the typo",
            goal_user_submission="Fix the typo",
            thread_id="t1",
            intent=None,
            routing_classification=None,
            total_tokens_used=0,
        ),
        intent_classifier=classifier,
        preferred_subagent=None,
        clarification_resume_text=None,
        clarification_resume_answers=None,
        ce=ce,
        goal_trace=_goal_trace(),
        state_manager=SimpleNamespace(loop_id="L1"),
        emit=AsyncMock(),
    )

    parent_config = {
        "callbacks": [MagicMock(name="graph-langfuse-handler")],
        "metadata": {"langfuse_trace_id": "trace-goal-1"},
    }
    await node_intent_classify(ctx, {}, parent_config)

    kwargs = classifier.classify_intake.await_args.kwargs
    assert kwargs["goal_trace"] is ctx.goal_trace
    assert kwargs["parent_runnable_config"] == parent_config
