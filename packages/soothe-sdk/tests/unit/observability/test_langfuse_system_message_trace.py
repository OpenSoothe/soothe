"""Tests for Langfuse CoreAgent system prompt visibility (IG-385)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe_sdk.observability.langfuse.callback_handler import (
    _apply_effective_system_prompt_to_batches,
)
from soothe_sdk.observability.langfuse.system_hint import (
    clear_langfuse_system_prompt_hint,
    get_langfuse_system_prompt_hint,
    publish_langfuse_system_prompt_hint,
    push_langfuse_system_prompt_hint,
    reset_langfuse_system_prompt_hint,
)


def _make_soothe_config(**langfuse_kwargs: Any) -> SimpleNamespace:
    """Build a ``SootheConfigLike`` stub without depending on package config models."""
    lf = {
        "enabled": False,
        "public_key": None,
        "secret_key": None,
        "host": None,
        "environment": None,
        "release": None,
        "sample_rate": None,
        "trace_name": None,
        "tags": None,
        "user_id": None,
    }
    lf.update(langfuse_kwargs)
    return SimpleNamespace(observability=SimpleNamespace(langfuse=SimpleNamespace(**lf)))


def test_context_hint_roundtrip() -> None:
    tok = push_langfuse_system_prompt_hint("SYS-A")
    try:
        assert get_langfuse_system_prompt_hint() == "SYS-A"
    finally:
        reset_langfuse_system_prompt_hint(tok)
    assert get_langfuse_system_prompt_hint() is None


def test_ensure_system_prepends_when_missing() -> None:
    out = _apply_effective_system_prompt_to_batches([[HumanMessage(content="hi")]], "BEEP")
    assert isinstance(out[0][0], SystemMessage)
    assert out[0][0].content == "BEEP"
    assert isinstance(out[0][1], HumanMessage)


def test_ensure_system_replaces_nonempty_first_system() -> None:
    """Effective middleware prompt must replace the shorter graph default system text."""
    out = _apply_effective_system_prompt_to_batches(
        [[SystemMessage(content="keep"), HumanMessage(content="hi")]],
        "<WORKSPACE_RULES>rules</WORKSPACE_RULES>",
    )
    assert out[0][0].content == "<WORKSPACE_RULES>rules</WORKSPACE_RULES>"
    assert isinstance(out[0][1], HumanMessage)


def test_ensure_system_replaces_empty_system() -> None:
    out = _apply_effective_system_prompt_to_batches(
        [[SystemMessage(content=""), HumanMessage(content="hi")]],
        "FILLED",
    )
    assert out[0][0].content == "FILLED"


def test_merge_uses_soothe_langfuse_handler() -> None:
    pytest.importorskip("langfuse")
    import soothe_sdk.observability.langfuse._handlers as handlers_mod
    from soothe_sdk.observability.langfuse import merge_langfuse_runnable_config
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handlers_mod._HANDLERS.clear()

    cfg = _make_soothe_config(enabled=True)
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(
        base, cfg, session_id="s1", run_name="soothe-dev:execute-step"
    )
    assert out["callbacks"]
    assert isinstance(out["callbacks"][-1], SootheLangfuseCallbackHandler)
    assert out["metadata"]["langfuse_trace_name"] == "soothe-dev:execute-step"


def test_handler_thread_key_hint_registry() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}

    cfg = {"configurable": {"thread_id": "fork-thread-1"}}
    handler.register_system_prompt_hint_for_config(cfg, "<WORKSPACE_RULES>x</WORKSPACE_RULES>")
    hint = handler._resolve_system_prompt_hint(metadata={"thread_id": "fork-thread-1"})
    assert hint == "<WORKSPACE_RULES>x</WORKSPACE_RULES>"
    handler.clear_system_prompt_hint_for_config(cfg)
    assert handler._resolve_system_prompt_hint(metadata={"thread_id": "fork-thread-1"}) is None


def test_on_chat_model_start_stores_traced_input_when_hint_set() -> None:
    pytest.importorskip("langfuse")
    from unittest.mock import patch

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}

    run_id = uuid4()
    cfg = {"configurable": {"thread_id": "t-trace"}}
    effective = "<WORKSPACE_RULES>use workspace</WORKSPACE_RULES>"
    handler.register_system_prompt_hint_for_config(cfg, effective)
    messages = [[SystemMessage(content="short default"), HumanMessage(content="step")]]
    langchain_handler = SootheLangfuseCallbackHandler.__mro__[1]
    with patch.object(
        langchain_handler,
        "on_chat_model_start",
        return_value=None,
    ) as parent:
        handler.on_chat_model_start(
            {},
            messages,
            run_id=run_id,
            metadata={"thread_id": "t-trace"},
        )
        parent.assert_called_once()
        patched_batches = parent.call_args[0][1]
        assert isinstance(patched_batches[0][0], SystemMessage)
        assert patched_batches[0][0].content == effective
    assert run_id in handler._generation_traced_inputs


def test_on_llm_end_passes_traced_input_to_parent() -> None:
    """Parent on_llm_end must receive patched inputs so Langfuse keeps the system message."""
    pytest.importorskip("langfuse")
    from unittest.mock import MagicMock, patch

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}

    run_id = uuid4()
    traced = [{"role": "system", "content": "<WORKSPACE_RULES>x</WORKSPACE_RULES>"}]
    handler._generation_traced_inputs[run_id] = traced

    langchain_handler = SootheLangfuseCallbackHandler.__mro__[1]
    with patch.object(langchain_handler, "on_llm_end", return_value=None) as parent:
        handler.on_llm_end(MagicMock(), run_id=run_id, inputs=[{"role": "user", "content": "hi"}])
        parent.assert_called_once()
        assert parent.call_args.kwargs["inputs"] == traced
    assert run_id not in handler._generation_traced_inputs


def test_on_chain_end_does_not_patch_chain_input() -> None:
    """System prompt mirroring is generation-only; chain spans keep original inputs."""
    pytest.importorskip("langfuse")
    from unittest.mock import patch as mpatch

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}
    handler._child_to_parent_run_id_map = {}

    chain_run = uuid4()
    langchain_handler = SootheLangfuseCallbackHandler.__mro__[1]
    with mpatch.object(langchain_handler, "on_chain_end", return_value=None) as parent:
        handler.on_chain_end({"messages": []}, run_id=chain_run)
        assert "inputs" not in parent.call_args.kwargs


def test_sanitize_cancelled_error_replaces_object_sentinel() -> None:
    """LangGraph cancels tasks with ``task.cancel(object())``; str() of that is unreadable."""
    pytest.importorskip("langfuse")
    import asyncio

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    sentinel = object()
    raw = asyncio.CancelledError(sentinel)
    assert "<object object at" in str(raw)

    sanitized = SootheLangfuseCallbackHandler._sanitize_cancelled_error(raw)
    assert isinstance(sanitized, asyncio.CancelledError)
    assert str(sanitized) == "Cancelled"


def test_sanitize_cancelled_error_passes_through_other_errors() -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    err = RuntimeError("boom")
    assert SootheLangfuseCallbackHandler._sanitize_cancelled_error(err) is err


def test_on_chain_error_sanitizes_cancelled_error() -> None:
    pytest.importorskip("langfuse")
    import asyncio
    from unittest.mock import patch as mpatch

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}
    handler._child_to_parent_run_id_map = {}

    chain_run = uuid4()
    raw = asyncio.CancelledError(object())
    langchain_handler = SootheLangfuseCallbackHandler.__mro__[1]
    with mpatch.object(langchain_handler, "on_chain_error", return_value=None) as parent:
        handler.on_chain_error(raw, run_id=chain_run)
        forwarded_error = parent.call_args[0][0]
        assert isinstance(forwarded_error, asyncio.CancelledError)
        assert str(forwarded_error) == "Cancelled"


def test_on_llm_error_sanitizes_cancelled_error() -> None:
    pytest.importorskip("langfuse")
    import asyncio
    from unittest.mock import patch as mpatch

    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handler = object.__new__(SootheLangfuseCallbackHandler)
    handler._system_hint_by_thread = {}
    handler._generation_traced_inputs = {}
    handler.runs = {}
    handler._child_to_parent_run_id_map = {}

    raw = asyncio.CancelledError(object())
    run_id = uuid4()
    langchain_handler = SootheLangfuseCallbackHandler.__mro__[1]
    with mpatch.object(langchain_handler, "on_llm_error", return_value=None) as parent:
        handler.on_llm_error(raw, run_id=run_id)
        forwarded_error = parent.call_args[0][0]
        assert isinstance(forwarded_error, asyncio.CancelledError)
        assert str(forwarded_error) == "Cancelled"


def test_publish_langfuse_system_prompt_hint_registers_on_handler() -> None:
    pytest.importorskip("langfuse")
    import soothe_sdk.observability.langfuse._handlers as handlers_mod
    from soothe_sdk.observability.langfuse import merge_langfuse_runnable_config
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    handlers_mod._HANDLERS.clear()
    cfg = _make_soothe_config(enabled=True)
    runnable = merge_langfuse_runnable_config(
        {"configurable": {"thread_id": "exec-1"}},
        cfg,
    )
    handler = runnable["callbacks"][-1]
    assert isinstance(handler, SootheLangfuseCallbackHandler)

    tok = publish_langfuse_system_prompt_hint(
        "<WORKSPACE_RULES>trace</WORKSPACE_RULES>",
        runnable_config=runnable,
    )
    try:
        assert get_langfuse_system_prompt_hint() == "<WORKSPACE_RULES>trace</WORKSPACE_RULES>"
        assert (
            handler._system_hint_by_thread["exec-1"] == "<WORKSPACE_RULES>trace</WORKSPACE_RULES>"
        )
    finally:
        clear_langfuse_system_prompt_hint(tok, runnable_config=runnable)
        assert "exec-1" not in handler._system_hint_by_thread
