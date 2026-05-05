"""Tests for Langfuse CoreAgent system prompt visibility (IG-385)."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.utils.observability.langfuse_callback_handler import _ensure_system_in_message_batches
from soothe.utils.observability.langfuse_system_hint import (
    get_langfuse_system_prompt_hint,
    push_langfuse_system_prompt_hint,
    reset_langfuse_system_prompt_hint,
)


def test_context_hint_roundtrip() -> None:
    tok = push_langfuse_system_prompt_hint("SYS-A")
    try:
        assert get_langfuse_system_prompt_hint() == "SYS-A"
    finally:
        reset_langfuse_system_prompt_hint(tok)
    assert get_langfuse_system_prompt_hint() is None


def test_ensure_system_prepends_when_missing() -> None:
    out = _ensure_system_in_message_batches([[HumanMessage(content="hi")]], "BEEP")
    assert isinstance(out[0][0], SystemMessage)
    assert out[0][0].content == "BEEP"
    assert isinstance(out[0][1], HumanMessage)


def test_ensure_system_keeps_nonempty_first_system() -> None:
    out = _ensure_system_in_message_batches(
        [[SystemMessage(content="keep"), HumanMessage(content="hi")]],
        "OTHER",
    )
    assert out[0][0].content == "keep"


def test_ensure_system_replaces_empty_system() -> None:
    out = _ensure_system_in_message_batches(
        [[SystemMessage(content=""), HumanMessage(content="hi")]],
        "FILLED",
    )
    assert out[0][0].content == "FILLED"


def test_merge_uses_soothe_langfuse_handler() -> None:
    pytest.importorskip("langfuse")
    from soothe.config import SootheConfig
    from soothe.config.models import LangfuseIntegrationConfig, ObservabilityConfig
    from soothe.utils.observability import langfuse as langfuse_util
    from soothe.utils.observability.langfuse import merge_langfuse_runnable_config
    from soothe.utils.observability.langfuse_callback_handler import SootheLangfuseCallbackHandler

    langfuse_util._HANDLERS.clear()

    obs = ObservabilityConfig(langfuse=LangfuseIntegrationConfig(enabled=True))
    cfg = SootheConfig(observability=obs)
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="s1")
    assert out["callbacks"]
    assert isinstance(out["callbacks"][-1], SootheLangfuseCallbackHandler)
