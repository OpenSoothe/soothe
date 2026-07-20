"""Shim: Coding CoreAgent builder (canonical in soothe-nano; host injections here)."""

from __future__ import annotations

from typing import Any

from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from soothe_nano.agent.builder import AgentBuilder as _NanoAgentBuilder

from soothe.foundation.sloop.middleware.intake_task_guard import IntakeOnlyTaskGuardMiddleware
from soothe.foundation.sloop.subagent_catalog import partition_subagent_specs


class AgentBuilder(_NanoAgentBuilder):
    """Soothe AgentBuilder: planner injection + intake-only catalog split."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._intake_only_specs: list[SubAgent | CompiledSubAgent] = []

    def _filter_subagents_for_graph(
        self, all_subagents: list[SubAgent | CompiledSubAgent]
    ) -> list[SubAgent | CompiledSubAgent]:
        catalog, intake = partition_subagent_specs(list(all_subagents))
        self._intake_only_specs = intake
        return catalog

    def _host_middleware_prefix(self) -> tuple:
        return (IntakeOnlyTaskGuardMiddleware(),)

    def build(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        if kwargs.get("planner") is None and "planner" not in kwargs:
            try:
                from soothe.runner.resolver import resolve_planner

                model = kwargs.get("model")
                default_model = model if not isinstance(model, str) else None
                kwargs["planner"] = resolve_planner(self._config, default_model)
            except Exception:
                pass
        agent = super().build(*args, **kwargs)
        from soothe.foundation.coreagent.coding.core_agent import CodingCoreAgent

        if not isinstance(agent, CodingCoreAgent):
            agent.__class__ = CodingCoreAgent
        agent.bind_intake_only_subagents(self._intake_only_specs)
        return agent


def create_soothe_agent(config: Any | None = None, **kwargs: Any):
    """Create Coding CoreAgent with soothe host injections."""
    builder = AgentBuilder(config)
    return builder.build(**kwargs)


__all__ = ["AgentBuilder", "create_soothe_agent"]
