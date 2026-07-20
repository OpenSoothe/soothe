"""Langfuse run_name for Executor streams (IG-377)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.config.models import LangfuseIntegrationConfig, ObservabilityConfig
from soothe.foundation.sloop.engine.executor import Executor


def test_executor_langfuse_merge_run_name_with_trace_name(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-dev"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    ex = Executor(MagicMock(), config=cfg)
    base = {"configurable": {"thread_id": "tid"}}
    out = ex._executor_langfuse_merge_for_stream(base, thread_id="sess-1")
    assert out["run_name"] == "soothe-dev:execute-step"


def test_executor_langfuse_merge_run_name_without_trace_name(monkeypatch) -> None:
    obs = ObservabilityConfig(langfuse=LangfuseIntegrationConfig(enabled=True))
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    ex = Executor(MagicMock(), config=cfg)
    base = {"configurable": {}}
    out = ex._executor_langfuse_merge_for_stream(base, thread_id="t1")
    assert out["run_name"] == "execute-step"


def test_executor_langfuse_merge_uses_goal_trace_when_present() -> None:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    goal_trace = MagicMock()
    goal_trace.enabled = True
    goal_trace.execute_invoke_config.return_value = {
        "run_name": "soothe-dev:execute-step",
        "metadata": {},
    }
    ex = Executor(MagicMock(), config=cfg, goal_trace=goal_trace)

    out = ex._executor_langfuse_merge_for_stream(
        {"configurable": {"thread_id": "fork-1"}},
        thread_id="fork-1",
    )

    goal_trace.execute_invoke_config.assert_called_once()
    _kwargs = goal_trace.execute_invoke_config.call_args.kwargs
    assert _kwargs["fork_thread_id"] == "fork-1"
    assert _kwargs["inherit_callbacks_from"] is None
    assert out["run_name"] == "soothe-dev:execute-step"


def test_executor_langfuse_merge_inherits_parent_callbacks_inside_graph() -> None:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    goal_trace = MagicMock()
    goal_trace.enabled = True
    parent_handler = MagicMock()
    parent_config = {
        "callbacks": [parent_handler],
        "metadata": {"langfuse_trace_id": "trace-goal-1"},
        "run_name": "soothe-dev:strange-loop-graph",
    }
    child_config = {
        "run_name": "soothe-dev:execute-step",
        "metadata": {"langfuse_trace_id": "trace-goal-1"},
    }
    goal_trace.execute_invoke_config.return_value = child_config
    ex = Executor(MagicMock(), config=cfg, goal_trace=goal_trace)

    with (
        patch("langgraph.config.get_config", return_value=parent_config),
        patch("langchain_core.runnables.config.merge_configs") as mock_merge,
    ):
        mock_merge.return_value = {
            **child_config,
            "callbacks": [parent_handler],
        }
        out = ex._executor_langfuse_merge_for_stream(
            {"configurable": {"thread_id": "fork-1"}},
            thread_id="fork-1",
        )

    goal_trace.execute_invoke_config.assert_called_once()
    assert (
        goal_trace.execute_invoke_config.call_args.kwargs["inherit_callbacks_from"] == parent_config
    )
    mock_merge.assert_called_once_with(parent_config, child_config)
    assert out["callbacks"] == [parent_handler]
