"""Regression tests for CoreAgentBuilder filesystem backend wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.foundation.coreagent.coding.builder import AgentBuilder


def test_build_passes_filesystem_backend_to_deepagents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filesystem ``backend`` must be passed to ``create_deep_agent``, not a config string."""
    fs_backend = MagicMock(name="filesystem_backend")
    captured: dict[str, object] = {}

    monkeypatch.setattr(AgentBuilder, "_initialize_backend", lambda self, policy: fs_backend)
    monkeypatch.setattr(AgentBuilder, "_load_plugins", lambda self: None)
    monkeypatch.setattr(AgentBuilder, "_resolve_memory", lambda self: None)
    monkeypatch.setattr(AgentBuilder, "_resolve_planner", lambda self, model: None)
    monkeypatch.setattr(AgentBuilder, "_resolve_policy", lambda self: None)
    monkeypatch.setattr("soothe.runner.resolver.resolve_tools", lambda *args, **kwargs: [])
    monkeypatch.setattr("soothe.runner.resolver.resolve_subagents", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "soothe.middleware._builder.build_soothe_middleware_stack",
        lambda *args, **kwargs: (),
    )
    monkeypatch.setattr(
        "soothe.middleware.model_call_profiler.install_model_call_profiler",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "soothe.middleware.model_call_profiler.is_profiler_enabled",
        lambda config: False,
    )

    def _fake_create_deep_agent(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("soothe_deepagents.create_deep_agent", _fake_create_deep_agent)

    monkeypatch.setattr(
        SootheConfig,
        "create_chat_model",
        lambda self, role: MagicMock(name="chat_model"),
    )

    AgentBuilder(SootheConfig()).build()

    assert captured["backend"] is fs_backend
    assert not isinstance(captured["backend"], str)
    assert captured["enable_general_purpose_subagent"] is False
    assert captured["filesystem_tools"] == [
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
    ]
    assert captured["parent_owned_state_keys"] == frozenset({"workspace"})
    assert captured["recursion_limit"] == 200
