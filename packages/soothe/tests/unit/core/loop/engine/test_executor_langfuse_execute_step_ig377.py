"""Langfuse run_name for Executor streams (IG-377)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.config import SootheConfig
from soothe.config.models import LangfuseIntegrationConfig, ObservabilityConfig
from soothe.foundation.sloop.engine.executor import Executor
from soothe.utils.observability.langfuse import merge_langfuse_runnable_config


def test_executor_langfuse_merge_run_name_with_trace_name(monkeypatch) -> None:
    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-dev"),
    )
    cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(
        "soothe.utils.observability.langfuse._merge.cached_langfuse_callback_handler",
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
        "soothe.utils.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )
    ex = Executor(MagicMock(), config=cfg)
    base = {"configurable": {}}
    out = ex._executor_langfuse_merge_for_stream(base, thread_id="t1")
    assert out["run_name"] == "execute-step"
