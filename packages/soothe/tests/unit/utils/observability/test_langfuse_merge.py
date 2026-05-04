"""Tests for Langfuse RunnableConfig merging (IG-367)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.config import SootheConfig
from soothe.config.models import LangfuseIntegrationConfig, ObservabilityConfig
from soothe.utils.observability import langfuse as langfuse_util
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config


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
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: None)
    out = merge_langfuse_runnable_config(base, cfg, session_id="t1")
    assert out is base


def test_merge_adds_callback_and_metadata(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: handler)
    base = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1")
    assert out is not base
    assert out["callbacks"][-1] is handler
    assert out["metadata"]["langfuse_session_id"] == "sess-1"
    assert out["run_name"] == "soothe-test"
    assert out["configurable"]["thread_id"] == "t1"


def test_merge_run_name_override(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-test"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: handler)
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
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: handler)
    base: dict = {"configurable": {"thread_id": "t1"}}
    out = merge_langfuse_runnable_config(base, cfg, session_id="sess-1")
    assert out["metadata"]["langfuse_tags"] == ["soothe", "cost"]
    assert out["metadata"]["langfuse_user_id"] == "tenant-alpha"


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
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: handler)
    base = {
        "metadata": {
            "langfuse_tags": ["caller"],
            "langfuse_user_id": "caller-user",
        },
    }
    out = merge_langfuse_runnable_config(base, cfg, session_id="s1")
    assert out["metadata"]["langfuse_tags"] == ["caller"]
    assert out["metadata"]["langfuse_user_id"] == "caller-user"
