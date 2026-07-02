"""Loop graph RunnableConfig + Langfuse bridge (RFC-220, IG-367, IG-396, IG-540)."""

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.foundation.sloop.orchestrator.runner import build_loop_graph_invoke_config
from soothe.utils.observability.langfuse import (
    build_goal_loop_langfuse_bootstrap,
    build_intake_langfuse_invoke_config,
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


def test_build_loop_graph_invoke_config_inherits_langfuse_bootstrap() -> None:
    """Graph invoke reuses bootstrap handler so intent-classify and graph share one trace."""
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    handler = MagicMock(name="shared_handler")
    bootstrap = {
        "configurable": {"thread_id": "loop-1"},
        "callbacks": [handler],
        "metadata": {
            "langfuse_session_id": "conv-thread-9",
            "loop_id": "loop-1",
            "langfuse_tags": ["goal_execution_loop", "strange-loop-graph"],
        },
        "run_name": "soothe-dev:strange-loop-graph",
    }

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
    ctx.langfuse_bootstrap = bootstrap
    ctx.proposal_queue = None

    with patch(
        "soothe.foundation.sloop.orchestrator.runner.merge_langfuse_runnable_config",
        return_value={
            "configurable": {"thread_id": "loop-1", "workspace": "/tmp/ws"},
            "callbacks": [handler],
            "metadata": {"loop_id": "loop-1"},
        },
    ) as m_merge:
        out = build_loop_graph_invoke_config(ctx)

    m_merge.assert_called_once()
    _args, kwargs = m_merge.call_args
    assert kwargs["inherit_callbacks_from"] is bootstrap
    assert kwargs["session_id"] == "conv-thread-9"
    assert _args[0]["configurable"]["thread_id"] == "loop-1"
    assert _args[0]["configurable"]["workspace"] == "/tmp/ws"
    assert out["callbacks"] == [handler]


def test_build_goal_loop_langfuse_bootstrap_sets_graph_tags() -> None:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = False

    out = build_goal_loop_langfuse_bootstrap(
        cfg,
        session_id="thread-1",
        loop_id="loop-1",
    )
    assert out["configurable"]["thread_id"] == "loop-1"


def test_build_intake_langfuse_invoke_config_uses_child_run_name() -> None:
    cfg = SootheConfig()
    cfg.observability.langfuse.enabled = True
    cfg.observability.langfuse.trace_name = "soothe-dev"

    bootstrap = {
        "configurable": {"thread_id": "loop-1"},
        "metadata": {"langfuse_session_id": "thread-1", "loop_id": "loop-1"},
    }

    with patch(
        "soothe.utils.observability.langfuse.merge_langfuse_runnable_config",
        return_value={"metadata": {}},
    ) as m_merge:
        build_intake_langfuse_invoke_config(
            cfg,
            langfuse_bootstrap=bootstrap,
            purpose="classify_intake",
            component="classifier.intake.primary",
        )

    _args, kwargs = m_merge.call_args
    assert kwargs["run_name"] == intent_classify_langfuse_run_display_name("soothe-dev")
    assert kwargs["inherit_callbacks_from"] is bootstrap
