"""Langfuse trace-level goal I/O patch (IG-395)."""

from unittest.mock import MagicMock, patch

import pytest


def test_loop_graph_langfuse_run_display_name() -> None:
    from soothe_sdk.observability.langfuse._names import (
        loop_graph_langfuse_run_display_name,
    )

    assert loop_graph_langfuse_run_display_name("soothe-dev") == "soothe-dev:nanoagent-graph"
    assert loop_graph_langfuse_run_display_name(None) == "nanoagent-graph"


def test_patch_langfuse_trace_goal_io_skips_without_handler() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse._trace_io import patch_langfuse_trace_goal_io

    with patch("langfuse.get_client") as gc:
        patch_langfuse_trace_goal_io(
            {},
            goal_text="g",
            output_text="o",
            trace_display_name="nanoagent-graph",
            public_key=None,
        )
    gc.assert_not_called()


def test_patch_langfuse_trace_goal_io_skips_without_trace_id() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse._trace_io import patch_langfuse_trace_goal_io
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    h = object.__new__(SootheLangfuseCallbackHandler)
    h.last_trace_id = None

    with patch("langfuse.get_client") as gc:
        patch_langfuse_trace_goal_io(
            {"callbacks": [h]},
            goal_text="goal",
            output_text="out",
            trace_display_name="x:nanoagent-graph",
            public_key="pk",
        )
    gc.assert_not_called()


def test_patch_langfuse_trace_goal_io_ingestion_skips_span() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse._trace_io import patch_langfuse_trace_goal_io
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    tid = "a" * 32
    h = object.__new__(SootheLangfuseCallbackHandler)
    h.last_trace_id = tid

    mock_client = MagicMock()

    with patch(
        "soothe_sdk.observability.langfuse._trace_io._merge_trace_fields_via_ingestion",
        return_value=True,
    ):
        with patch("langfuse.get_client", return_value=mock_client):
            patch_langfuse_trace_goal_io(
                {"callbacks": [h]},
                goal_text="my goal",
                output_text="final answer",
                trace_display_name="soothe-dev:nanoagent-graph",
                session_id="thread-1",
                public_key="pk-test",
            )

    mock_client.start_span.assert_not_called()
    mock_client.flush.assert_called_once()


def test_patch_langfuse_trace_goal_io_fallback_span_updates_name() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse._trace_io import patch_langfuse_trace_goal_io
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    tid = "a" * 32
    h = object.__new__(SootheLangfuseCallbackHandler)
    h.last_trace_id = tid

    mock_span = MagicMock()
    mock_client = MagicMock()
    mock_client.start_span.return_value = mock_span

    with patch(
        "soothe_sdk.observability.langfuse._trace_io._merge_trace_fields_via_ingestion",
        return_value=False,
    ):
        with patch("langfuse.get_client", return_value=mock_client):
            patch_langfuse_trace_goal_io(
                {"callbacks": [h]},
                goal_text="my goal",
                output_text="final answer",
                trace_display_name="soothe-dev:nanoagent-graph",
                public_key="pk-test",
            )

    mock_client.start_span.assert_called_once()
    assert mock_client.start_span.call_args[1]["trace_context"]["trace_id"] == tid
    assert mock_client.start_span.call_args[1]["name"] == "soothe-dev:nanoagent-graph"
    mock_span.update_trace.assert_called_once_with(
        name="soothe-dev:nanoagent-graph",
        input="my goal",
        output="final answer",
    )
    mock_span.end.assert_called_once()
    mock_client.flush.assert_called_once()


def test_merge_trace_fields_via_ingestion_enqueues() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse._trace_io import _merge_trace_fields_via_ingestion

    tid = "b" * 32
    mock_rs = MagicMock()
    mock_client = MagicMock()
    mock_client._resources = mock_rs
    mock_client.create_trace_id.return_value = "evt1"

    ok = _merge_trace_fields_via_ingestion(
        mock_client,
        trace_id=tid,
        display_name="soothe-dev:nanoagent-graph",
        input_text="in",
        output_text="out",
        session_id="sid",
    )
    assert ok is True
    mock_rs.add_trace_task.assert_called_once()
    evt = mock_rs.add_trace_task.call_args[0][0]
    assert evt["type"] == "trace-create"
    body = evt["body"]
    assert body.id == tid
    assert body.name == "soothe-dev:nanoagent-graph"
    assert body.input == "in"
    assert body.output == "out"
    assert body.session_id == "sid"
