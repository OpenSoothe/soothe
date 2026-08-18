"""Root standalone LLM calls must honor goal-loop ``trace_context`` (IG-540)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def test_langfuse_trace_pinned_parent_injects_trace_context() -> None:
    from soothe_sdk.observability.langfuse.callback_handler import _LangfuseTracePinnedParent

    client = MagicMock()
    client.start_observation.return_value = MagicMock()
    trace_context = {"trace_id": "trace-goal-1"}

    pinned = _LangfuseTracePinnedParent(client, trace_context)
    pinned.start_observation(as_type="generation", name="intake-classify")

    client.start_observation.assert_called_once_with(
        as_type="generation",
        name="intake-classify",
        trace_context=trace_context,
    )


def test_langfuse_trace_pinned_parent_preserves_explicit_trace_context() -> None:
    from soothe_sdk.observability.langfuse.callback_handler import _LangfuseTracePinnedParent

    client = MagicMock()
    explicit = {"trace_id": "other-trace"}
    pinned = _LangfuseTracePinnedParent(client, {"trace_id": "trace-goal-1"})
    pinned.start_observation(as_type="generation", trace_context=explicit)

    client.start_observation.assert_called_once_with(
        as_type="generation",
        trace_context=explicit,
    )


def test_soothe_handler_wraps_root_client_when_trace_context_set() -> None:
    pytest.importorskip("langfuse")
    from langfuse._client.client import Langfuse

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
        _LangfuseTracePinnedParent,
    )

    handler = SootheLangfuseCallbackHandler(trace_context={"trace_id": "trace-goal-1"})
    handler.client = MagicMock(spec=Langfuse)

    wrapped = handler._get_parent_observation(None)
    assert isinstance(wrapped, _LangfuseTracePinnedParent)


def test_soothe_handler_does_not_wrap_when_parent_run_exists() -> None:
    pytest.importorskip("langfuse")
    from uuid import uuid4

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
        _LangfuseTracePinnedParent,
    )

    handler = SootheLangfuseCallbackHandler(trace_context={"trace_id": "trace-goal-1"})
    parent_run_id = uuid4()
    parent_obs = MagicMock()
    handler.runs[parent_run_id] = parent_obs

    obs = handler._get_parent_observation(parent_run_id)
    assert obs is parent_obs
    assert not isinstance(obs, _LangfuseTracePinnedParent)
