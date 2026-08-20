"""Intake station Langfuse parent span + nested pass run names."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe_sdk.intention.models import TaskComplexity

from soothe.config import SootheConfig
from soothe.sloop.intention import IntentClassification
from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.stages.preprocess.intake import node_intent_classify
from soothe.utils.observability.langfuse import (
    GoalLoopTrace,
    open_intake_langfuse_span,
)


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


def test_open_intake_span_is_inert_without_trace() -> None:
    assert open_intake_langfuse_span(None).parent_span_id is None
    assert open_intake_langfuse_span(_goal_trace(enabled=False)).parent_span_id is None
    assert open_intake_langfuse_span(_goal_trace(trace_id=None)).parent_span_id is None


def test_open_intake_span_starts_named_span_on_goal_trace() -> None:
    span = MagicMock()
    span.id = "span-intake-1"
    client = MagicMock()
    client.start_observation.return_value = span

    with patch(
        "soothe.utils.observability.langfuse._intake_span.host_langfuse_client",
        return_value=client,
    ):
        handle = open_intake_langfuse_span(_goal_trace(), input_text="analyze repo")

    kwargs = client.start_observation.call_args.kwargs
    assert kwargs["trace_context"] == {"trace_id": "trace-goal-1"}
    assert kwargs["name"] == "soothe-dev:intake"
    assert kwargs["input"] == "analyze repo"
    assert kwargs["metadata"]["soothe_station"] == "intake"
    assert handle.parent_span_id == "span-intake-1"

    handle.end(output="simple")
    handle.end()
    span.update.assert_called_once_with(output="simple")
    span.end.assert_called_once()


def test_open_intake_span_survives_client_failure() -> None:
    with patch(
        "soothe.utils.observability.langfuse._intake_span.host_langfuse_client",
        side_effect=RuntimeError("no langfuse"),
    ):
        handle = open_intake_langfuse_span(_goal_trace())

    assert handle.parent_span_id is None
    handle.end(output="simple")


def test_intake_invoke_config_nests_passes_under_span() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    nested = _goal_trace().with_intake_parent_span("span-intake-1")
    out = nested.intake_invoke_config(
        purpose="classify_social_gate",
        component="classifier.intake.classify",
        phase="intake_classify",
    )

    handlers = [h for h in out["callbacks"] if isinstance(h, SootheLangfuseCallbackHandler)]
    assert len(handlers) == 1
    assert handlers[0].trace_context == {
        "trace_id": "trace-goal-1",
        "parent_span_id": "span-intake-1",
    }
    assert out["run_name"] == "soothe-dev:intake-classify"
    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"


def test_intake_invoke_config_without_span_stays_trace_pinned() -> None:
    pytest.importorskip("langfuse")

    base = _goal_trace()
    assert base.with_intake_parent_span(None) is base

    out = base.intake_invoke_config(
        purpose="classify_social_gate",
        component="classifier.intake.classify",
        phase="intake_classify",
    )
    handler = out["callbacks"][0]
    assert handler.trace_context == {"trace_id": "trace-goal-1"}
    assert out["run_name"] == "soothe-dev:intake-classify"


def test_intake_invoke_config_inherits_graph_handler() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    graph_handler = SootheLangfuseCallbackHandler(trace_context={"trace_id": "trace-goal-1"})
    nested = _goal_trace().with_intake_parent_span("span-intake-1")
    out = nested.intake_invoke_config(
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
