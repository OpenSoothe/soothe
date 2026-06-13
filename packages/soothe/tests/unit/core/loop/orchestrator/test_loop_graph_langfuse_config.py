"""Loop graph RunnableConfig + Langfuse bridge (RFC-220, IG-367, IG-396)."""

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.foundation.loop.orchestrator.runner import build_loop_graph_invoke_config


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
        "soothe.foundation.loop.orchestrator.runner.merge_langfuse_runnable_config",
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
