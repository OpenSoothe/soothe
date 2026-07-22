"""Soothe CoreAgent builder: host injections over soothe-nano builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from soothe_nano.agent import builder as nano_builder

from soothe.sloop.goal_step_guard import GoalStepGuardMiddleware
from soothe.sloop.intake_task_guard import IntakeOnlyTaskGuardMiddleware
from soothe.sloop.subagent_catalog import partition_subagent_specs

if TYPE_CHECKING:
    from soothe.identity.runtime import IdentityRuntime


class AgentBuilder(nano_builder.AgentBuilder):
    """Soothe AgentBuilder: planner injection + intake-only catalog split."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._intake_only_specs: list[SubAgent | CompiledSubAgent] = []
        self._identity_runtime: IdentityRuntime | None = None

    def _filter_subagents_for_graph(
        self, all_subagents: list[SubAgent | CompiledSubAgent]
    ) -> list[SubAgent | CompiledSubAgent]:
        catalog, intake = partition_subagent_specs(list(all_subagents))
        self._intake_only_specs = intake
        return catalog

    def _host_middleware_prefix(self) -> tuple:
        # Clear intake-only preferred_subagent before nano ToolEnforcement.
        from soothe.identity.middleware import IdentityMiddleware

        prefix: list[Any] = []
        if self._identity_runtime is not None and self._identity_runtime.enabled:
            prefix.append(IdentityMiddleware(self._identity_runtime))
        prefix.append(IntakeOnlyTaskGuardMiddleware())
        return tuple(prefix)

    def _host_middleware_suffix(self) -> tuple:
        # Apply after ToolEnforcement so step/synthesis configurables win.
        return (GoalStepGuardMiddleware(),)

    def build(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        # Install host daemon kill guards before toolkit resolution (nano hook).
        from soothe.security.daemon_kill_guards import ensure_daemon_kill_guards_installed

        ensure_daemon_kill_guards_installed()

        self._identity_runtime = kwargs.pop("identity_runtime", None)
        if kwargs.get("planner") is None and "planner" not in kwargs:
            try:
                from soothe.runner.resolver import resolve_planner

                model = kwargs.get("model")
                default_model = model if not isinstance(model, str) else None
                kwargs["planner"] = resolve_planner(self._config, default_model)
            except Exception:
                pass
        try:
            agent = super().build(*args, **kwargs)
        finally:
            self._identity_runtime = None
        from soothe.coreagent.core_agent import CodingCoreAgent

        if not isinstance(agent, CodingCoreAgent):
            agent.__class__ = CodingCoreAgent
        agent.bind_intake_only_subagents(self._intake_only_specs)
        return agent


def create_soothe_agent(config: Any | None = None, **kwargs: Any):
    """Create Coding CoreAgent with soothe host injections."""
    builder = AgentBuilder(config)
    return builder.build(**kwargs)


__all__ = ["AgentBuilder", "create_soothe_agent"]
