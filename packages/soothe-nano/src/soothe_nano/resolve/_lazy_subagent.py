"""Deferred subagent graph compilation for faster CoreAgent startup."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_BUILTIN_DESCRIPTIONS: dict[str, str] = {
    "plan": (
        "Planning delegate with agentic loops: iteratively runs multiple readonly "
        "recon passes per round (and multiple collection rounds) to gather workspace "
        "evidence, then iteratively refines a full markdown execution plan before "
        "returning one report. Use when the main thread needs structured recon-plus-plan "
        "without doing every recon and rewrite itself."
    ),
    "explorer": (
        "Deep code explorer subagent: iterative readonly repository reconnaissance via "
        "glob/grep/read_file/ls and structured synthesis."
    ),
    "deep_research": ("Public-domain research subagent for web, academic, and URL sources."),
}


def subagent_description(name: str, factory: Callable[..., Any]) -> str:
    """Resolve task-tool description without compiling the subagent graph."""
    plugin_desc = getattr(factory, "_subagent_description", None)
    if isinstance(plugin_desc, str) and plugin_desc.strip():
        return plugin_desc
    return _BUILTIN_DESCRIPTIONS.get(name, f"Subagent '{name}'.")


class LazySubagentRunnable:
    """Runnable wrapper that compiles a subagent graph on first invoke."""

    def __init__(
        self,
        factory: Callable[..., Any],
        kwargs: dict[str, Any],
        name: str,
        *,
        materialize: Callable[[Callable[..., Any], dict[str, Any]], Any] | None = None,
        pending_config: dict[str, Any] | None = None,
    ) -> None:
        self._factory = factory
        self._kwargs = kwargs
        self._name = name
        self._materialize_fn = materialize
        self._pending_config = pending_config
        self._delegate: Any | None = None
        self._lock = threading.Lock()

    def _materialize(self) -> Any:
        if self._delegate is not None:
            return self._delegate
        with self._lock:
            if self._delegate is not None:
                return self._delegate
            materialize = self._materialize_fn or _default_materialize
            spec = materialize(self._factory, self._kwargs)
            runnable = spec["runnable"] if isinstance(spec, dict) else spec.runnable
            if self._pending_config:
                runnable = runnable.with_config(self._pending_config)
            self._delegate = runnable
            logger.info("Materialized lazy subagent '%s'", self._name)
            return self._delegate

    def with_config(self, config: Any = None, **kwargs: Any) -> LazySubagentRunnable:
        merged = dict(self._pending_config or {})
        if config:
            if isinstance(config, dict):
                merged.update(config)
            else:
                merged["config"] = config
        merged.update(kwargs)
        cloned = LazySubagentRunnable(
            self._factory,
            self._kwargs,
            self._name,
            materialize=self._materialize_fn,
            pending_config=merged or None,
        )
        if self._delegate is not None:
            cloned._delegate = self._delegate.with_config(config, **kwargs)
        return cloned

    def invoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._materialize().invoke(state, config, **kwargs)

    async def ainvoke(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return await self._materialize().ainvoke(state, config, **kwargs)

    def stream(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        return self._materialize().stream(state, config, **kwargs)

    async def astream(
        self,
        state: dict[str, Any],
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        async for chunk in self._materialize().astream(state, config, **kwargs):
            yield chunk

    def __getattr__(self, name: str) -> Any:
        return getattr(self._materialize(), name)


def _default_materialize(factory: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
    from soothe_nano.resolve import _resolver_tools

    return _resolver_tools._call_subagent_factory(factory, kwargs)


def lazy_compiled_subagent_spec(
    name: str,
    factory: Callable[..., Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build a CompiledSubAgent dict without compiling the underlying graph."""
    return {
        "name": name,
        "description": subagent_description(name, factory),
        "runnable": LazySubagentRunnable(factory, kwargs, name),
    }
