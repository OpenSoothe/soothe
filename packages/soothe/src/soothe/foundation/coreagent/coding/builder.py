"""Shim: Coding CoreAgent builder (canonical in soothe-nano; planner injected here)."""

from __future__ import annotations

from typing import Any

from soothe_nano.agent.builder import AgentBuilder as _NanoAgentBuilder


class AgentBuilder(_NanoAgentBuilder):
    """Soothe AgentBuilder that injects StrangeLoop planner when omitted."""

    def build(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        if kwargs.get("planner") is None and "planner" not in kwargs:
            try:
                from soothe.runner.resolver import resolve_planner

                model = kwargs.get("model")
                default_model = model if not isinstance(model, str) else None
                kwargs["planner"] = resolve_planner(self._config, default_model)
            except Exception:
                pass
        if kwargs.get("memory_store") is None and "memory_store" not in kwargs:
            # Prefer nano resolve_memory; fall back to soothe resolver
            pass
        agent = super().build(*args, **kwargs)
        from soothe.foundation.coreagent.coding.core_agent import CodingCoreAgent

        if not isinstance(agent, CodingCoreAgent):
            agent.__class__ = CodingCoreAgent
        return agent


def create_soothe_agent(config: Any | None = None, **kwargs: Any):
    """Create Coding CoreAgent with soothe host injections."""
    builder = AgentBuilder(config)
    return builder.build(**kwargs)


__all__ = ["AgentBuilder", "create_soothe_agent"]
