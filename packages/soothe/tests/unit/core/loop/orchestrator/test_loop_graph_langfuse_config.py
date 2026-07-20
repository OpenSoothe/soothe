"""Loop graph RunnableConfig + Langfuse bridge (RFC-220, IG-367, IG-396, IG-540)."""

from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.foundation.sloop.orchestrator.runner import build_loop_graph_invoke_config
from soothe.utils.observability.langfuse import (
    GoalLoopTrace,
    SootheLangfuse,
    intent_classify_langfuse_run_display_name,
)


def test_build_loop_graph_invoke_config_keeps_loop_id_as_graph_thread() -> None:
    """LangGraph configurable.thread_id stays loop_id; metadata carries loop_id for dashboards."""
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = False

    mock_al = MagicMock()
    mock_al.config = cfg

    mock_sm = MagicMock()
    mock_sm.loop_id = "loop-abc"

    mock_ls = MagicMock()
    mock_ls.thread_id = "thread-xyz"

    ctx = MagicMock()
    ctx.strange_loop = mock_al
    ctx.state_manager = mock_sm
    ctx.loop_state = mock_ls
    ctx.goal_trace = None
    ctx.proposal_queue = None

    out = build_loop_graph_invoke_config(ctx)

    assert out["configurable"]["thread_id"] == "loop-abc"
    meta = out["metadata"]
    assert meta["loop_id"] == "loop-abc"
    assert meta["soothe_component"] == "strange_loop_graph"
    assert "goal_execution_loop" in meta["langfuse_tags"]


def test_build_loop_graph_invoke_config_passes_conversation_thread_to_langfuse_merge() -> None:
    """``merge_langfuse_runnable_config`` receives conversation thread_id as session_id."""
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True

    mock_al = MagicMock()
    mock_al.config = cfg

    mock_sm = MagicMock()
    mock_sm.loop_id = "loop-1"

    mock_ls = MagicMock()
    mock_ls.thread_id = "conv-thread-9"

    ctx = MagicMock()
    ctx.strange_loop = mock_al
    ctx.state_manager = mock_sm
    ctx.loop_state = mock_ls
    ctx.goal_trace = None
    ctx.proposal_queue = None

    with patch(
        "soothe.foundation.sloop.orchestrator.runner.merge_langfuse_runnable_config",
        return_value={
            "configurable": {"thread_id": "loop-1"},
            "metadata": {"langfuse_session_id": "conv-thread-9"},
        },
    ) as m_merge:
        out = build_loop_graph_invoke_config(ctx)

    m_merge.assert_called_once()
    _args, kwargs = m_merge.call_args
    assert kwargs["session_id"] == "conv-thread-9"
    assert kwargs["loop_id"] == "loop-1"
    assert (
        kwargs["run_name"].endswith(":strange-loop-graph")
        or kwargs["run_name"] == "strange-loop-graph"
    )
    assert out["metadata"]["loop_id"] == "loop-1"


def test_build_loop_graph_invoke_config_uses_goal_trace_pinned_id() -> None:
    """Graph invoke pins handler to goal trace id so intent-classify shares one trace."""
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    goal_trace = GoalLoopTrace(
        soothe_config=cfg,
        trace_id="trace-goal-1",
        session_id="conv-thread-9",
        loop_id="loop-1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    mock_al = MagicMock()
    mock_al.config = cfg

    mock_sm = MagicMock()
    mock_sm.loop_id = "loop-1"

    mock_ls = MagicMock()
    mock_ls.thread_id = "conv-thread-9"
    mock_ls.workspace = "/tmp/ws"

    ctx = MagicMock()
    ctx.strange_loop = mock_al
    ctx.state_manager = mock_sm
    ctx.loop_state = mock_ls
    ctx.goal_trace = goal_trace
    ctx.proposal_queue = None

    out = build_loop_graph_invoke_config(ctx)

    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"
    assert out["configurable"]["thread_id"] == "loop-1"
    assert out["configurable"]["workspace"] == "/tmp/ws"
    assert out["run_name"] == "soothe-dev:strange-loop-graph"
    assert "callbacks" in out


def test_begin_goal_loop_pins_trace_id(monkeypatch) -> None:
    pytest.importorskip("langfuse")

    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"
    cfg.observability.langfuse.public_key = "pk-test"

    monkeypatch.setattr(
        "soothe.utils.observability.langfuse._goal_loop.allocate_langfuse_trace_id",
        lambda _c: "trace-goal-1",
    )

    goal_trace = SootheLangfuse(cfg).begin_goal_loop(
        session_id="thread-1",
        loop_id="loop-1",
    )
    assert goal_trace is not None
    assert goal_trace.trace_id == "trace-goal-1"
    assert goal_trace.trace_display_name == "soothe-dev:strange-loop-graph"


def test_begin_goal_loop_disabled_returns_none() -> None:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = False
    assert SootheLangfuse(cfg).begin_goal_loop(session_id="thread-1", loop_id="loop-1") is None


def test_goal_trace_intake_invoke_config_pins_trace_id() -> None:
    pytest.importorskip("langfuse")
    from soothe_nano.utils.observability.langfuse_callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    goal_trace = GoalLoopTrace(
        soothe_config=cfg,
        trace_id="trace-goal-1",
        session_id="thread-1",
        loop_id="loop-1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    out = goal_trace.intake_invoke_config(
        purpose="classify_intake",
        component="classifier.intake.primary",
    )

    assert out["callbacks"]
    handler = out["callbacks"][0]
    assert isinstance(handler, SootheLangfuseCallbackHandler)
    assert handler.trace_context == {"trace_id": "trace-goal-1"}
    assert out["run_name"] == intent_classify_langfuse_run_display_name("soothe-dev")
    assert out["metadata"]["langfuse_trace_name"] == "soothe-dev:strange-loop-graph"
    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"


def test_goal_trace_execute_invoke_config_pins_trace_id() -> None:
    pytest.importorskip("langfuse")
    from soothe_nano.utils.observability.langfuse._names import (
        execute_step_langfuse_run_display_name,
    )
    from soothe_nano.utils.observability.langfuse_callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    goal_trace = GoalLoopTrace(
        soothe_config=cfg,
        trace_id="trace-goal-1",
        session_id="thread-1",
        loop_id="loop-1",
        trace_display_name="soothe-dev:strange-loop-graph",
    )

    out = goal_trace.execute_invoke_config(
        fork_thread_id="fork-step-1",
        configurable={"thread_id": "fork-step-1", "workspace": "/tmp/ws"},
    )

    assert out["callbacks"]
    handler = out["callbacks"][0]
    assert isinstance(handler, SootheLangfuseCallbackHandler)
    assert handler.trace_context == {"trace_id": "trace-goal-1"}
    assert out["run_name"] == execute_step_langfuse_run_display_name("soothe-dev")
    assert out["metadata"]["langfuse_trace_id"] == "trace-goal-1"
    assert out["metadata"]["soothe_component"] == "execute_step"
    assert "execute-step" in out["metadata"]["langfuse_tags"]
    assert out["configurable"]["thread_id"] == "fork-step-1"
