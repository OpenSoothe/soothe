"""Tests for deferred subagent graph compilation."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.runner.resolver._lazy_subagent import LazySubagentRunnable, lazy_compiled_subagent_spec


def test_lazy_subagent_defers_factory_until_invoke() -> None:
    """Subagent factories must not run during resolve_subagents registration."""
    inner = MagicMock()
    inner.invoke.return_value = {"messages": []}
    factory = MagicMock(return_value={"name": "demo", "description": "d", "runnable": inner})

    spec = lazy_compiled_subagent_spec("demo", factory, {"model": "test"})
    assert spec["name"] == "demo"
    factory.assert_not_called()

    spec["runnable"].invoke({"messages": []})
    factory.assert_called_once_with(model="test")
    inner.invoke.assert_called_once()


def test_lazy_subagent_materializes_once() -> None:
    inner = MagicMock()
    inner.invoke.return_value = {"messages": []}
    factory = MagicMock(return_value={"name": "demo", "description": "d", "runnable": inner})

    runnable = LazySubagentRunnable(factory, {}, "demo")
    runnable.invoke({"messages": []})
    runnable.invoke({"messages": []})

    factory.assert_called_once()


def test_lazy_subagent_with_config_applied_on_materialize() -> None:
    inner = MagicMock()
    configured = MagicMock()
    inner.with_config.return_value = configured
    configured.invoke.return_value = {"messages": []}
    factory = MagicMock(return_value={"name": "demo", "description": "d", "runnable": inner})

    runnable = LazySubagentRunnable(
        factory,
        {},
        "demo",
        pending_config={"run_name": "demo"},
    )
    runnable.invoke({"messages": []})

    inner.with_config.assert_called_once_with({"run_name": "demo"})
    configured.invoke.assert_called_once()
