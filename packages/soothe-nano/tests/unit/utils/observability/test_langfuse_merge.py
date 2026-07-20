"""Tests for Langfuse RunnableConfig merging (IG-367)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from soothe_sdk.observability.langfuse import merge_langfuse_runnable_config

from soothe_nano.config import SootheConfig
from soothe_nano.config.models import LangfuseIntegrationConfig, ObservabilityConfig


def test_merge_returns_base_when_disabled() -> None:
    cfg = SootheConfig()
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="t1")
    assert out is base
    assert "callbacks" not in out


def test_merge_returns_base_when_handler_unavailable(monkeypatch) -> None:
    obs = ObservabilityConfig(langfuse=LangfuseIntegrationConfig(enabled=True))
    cfg = SootheConfig(observability=obs)
    base = {"configurable": {"thread_id": "t1"}}
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: None,
    )
    out = merge_langfuse_runnable_config(base, cfg, session_id="t1")
    assert out is base


def test_callback_handler_returns_none_when_langfuse_placeholder_loaded(monkeypatch) -> None:
    pytest.importorskip("langfuse.langchain")
    import soothe_sdk.observability.langfuse._handlers as handlers_mod
    import soothe_sdk.observability.langfuse.callback_handler as callback_module

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, public_key="pk-test"),
    )
    cfg = SootheConfig(observability=obs)

    class PlaceholderHandler:
        pass

    handlers_mod._HANDLERS.clear()
    monkeypatch.setattr(callback_module, "LANGFUSE_AVAILABLE", False)
    monkeypatch.setattr(callback_module, "SootheLangfuseCallbackHandler", PlaceholderHandler)

    assert handlers_mod.cached_langfuse_callback_handler(cfg) is None


def test_merge_adds_callback_and_metadata(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1")
    assert out is not base
    assert out["callbacks"][-1] is handler
    assert out["metadata"]["langfuse_session_id"] == "sess-1"
    assert out["metadata"]["thread_id"] == "sess-1"
    assert out["run_name"] == "soothe-test"
    assert out["configurable"]["thread_id"] == "t1"


def test_merge_run_name_override(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(
        base, cfg, session_id="sess-1", run_name="soothe-test:plan-assess"
    )
    assert out["run_name"] == "soothe-test:plan-assess"


def test_merge_adds_langfuse_tags_and_user_id_from_config(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(
            enabled=True,
            trace_name="soothe-test",
            tags=[" soothe ", "cost"],
            user_id="tenant-alpha",
        ),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base: dict = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1")
    assert out["metadata"]["langfuse_tags"] == ["soothe", "cost"]
    assert out["metadata"]["langfuse_user_id"] == "tenant-alpha"


def test_merge_adds_loop_id_to_metadata(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base: dict = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1", loop_id="loop-42")
    assert out["metadata"]["loop_id"] == "loop-42"


def test_merge_does_not_override_existing_loop_id(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base = {"metadata": {"loop_id": "existing-loop"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="s1", loop_id="new-loop")
    assert out["metadata"]["loop_id"] == "existing-loop"


def test_merge_omits_loop_id_when_none(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base: dict = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1")
    assert "loop_id" not in out.get("metadata", {})


def test_merge_skips_handler_append_when_inherit_carries_same_handler(monkeypatch) -> None:
    """Nested CoreAgent streams must not stack duplicate Langfuse handlers (goal synthesis)."""
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = SootheLangfuseCallbackHandler()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    parent = {"callbacks": [handler]}
    base = {"configurable": {"thread_id": "syn-thread"}}
    out = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id="sess-1",
        run_name="soothe-test:goal-synthesis",
        inherit_callbacks_from=parent,
    )
    assert "callbacks" not in out
    assert out["run_name"] == "soothe-test:goal-synthesis"
    assert out["metadata"]["langfuse_session_id"] == "sess-1"


def test_merge_reuses_inherited_handler_not_cached(monkeypatch) -> None:
    """Goal-loop bootstrap handler must not be replaced by the process-wide cached handler."""
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    from soothe_nano.config.models import LangfuseIntegrationConfig, ObservabilityConfig

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    cached = SootheLangfuseCallbackHandler()
    inherited = SootheLangfuseCallbackHandler(trace_context={"trace_id": "shared-trace"})
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: cached,
    )

    parent = {"callbacks": [inherited]}
    base = {"configurable": {"thread_id": "loop-1"}, "callbacks": [inherited]}
    out = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id="sess-1",
        run_name="soothe-test:nanoagent-graph",
        inherit_callbacks_from=parent,
    )
    assert out["callbacks"] == [inherited]
    assert out["callbacks"][0] is not cached


def test_merge_appends_handler_when_inherit_lacks_soothe_handler(monkeypatch) -> None:
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = SootheLangfuseCallbackHandler()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    parent = {"callbacks": [MagicMock()]}
    base = {"configurable": {"thread_id": "syn-thread"}}
    out = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id="sess-1",
        run_name="soothe-test:goal-synthesis",
        inherit_callbacks_from=parent,
    )
    assert out["callbacks"][-1] is handler


def test_merge_uses_pinned_trace_id_for_fresh_handler(monkeypatch) -> None:
    """Goal-loop stages get independent handlers pinned to the same trace id."""
    pytest.importorskip("langfuse")
    from soothe_sdk.observability.langfuse.callback_handler import (
        SootheLangfuseCallbackHandler,
    )

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    cached = SootheLangfuseCallbackHandler()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: cached,
    )
    base: dict = {"configurable": {"thread_id": "loop-1"}}
    out = merge_langfuse_runnable_config(
        base,
        cfg,
        session_id="sess-1",
        run_name="soothe-test:intake-classify",
        pinned_trace_id="shared-trace-99",
    )
    assert out["callbacks"]
    handler = out["callbacks"][0]
    assert handler is not cached
    assert handler.trace_context == {"trace_id": "shared-trace-99"}
    assert out["metadata"]["langfuse_trace_id"] == "shared-trace-99"


def test_merge_does_not_override_existing_langfuse_trace_metadata(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(
            enabled=True,
            tags=["from-config"],
            user_id="config-user",
        ),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe_sdk.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    base = {
        "metadata": {
            "langfuse_tags": ["caller"],
            "langfuse_user_id": "caller-user",
        },
    }
    out = merge_langfuse_runnable_config(base, cfg, session_id="s1")
    assert out["metadata"]["langfuse_tags"] == ["caller"]
    assert out["metadata"]["langfuse_user_id"] == "caller-user"
