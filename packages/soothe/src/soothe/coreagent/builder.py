"""Soothe CoreAgent builder: host injections over soothe-nano builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from soothe_nano.agent import builder as nano_builder

from soothe.sloop.middleware import (
    GoalStepGuardMiddleware,
    IntakeOnlyTaskGuardMiddleware,
    WestWorldMiddleware,
)
from soothe.sloop.utils.subagent_catalog import partition_subagent_specs

if TYPE_CHECKING:
    from soothe.identity.runtime import IdentityRuntime


class AgentBuilder(nano_builder.AgentBuilder):
    """Soothe AgentBuilder: host injections + intake-only catalog split."""

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
        from soothe.sloop.middleware import (
            AskUserPromptMiddleware,
            DecomposeTaskMiddleware,
            EvalStepMiddleware,
            GeneralPurposeVariantGuardMiddleware,
        )

        return (
            GoalStepGuardMiddleware(),
            WestWorldMiddleware(),
            DecomposeTaskMiddleware(),
            GeneralPurposeVariantGuardMiddleware(),
            EvalStepMiddleware(),
            AskUserPromptMiddleware(),
        )

    def build(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        # Install host daemon kill guards before toolkit resolution (nano hook).
        from soothe.security.daemon_kill_guards import ensure_daemon_kill_guards_installed

        ensure_daemon_kill_guards_installed()

        self._identity_runtime = kwargs.pop("identity_runtime", None)

        # Inject host-only tools not resolved from config.
        from soothe.coreagent.tools import (
            build_ask_user_tool,
            build_request_plan_mode_tool,
        )

        extra_tools = list(kwargs.get("tools") or [])
        extra_tools.append(build_request_plan_mode_tool())
        extra_tools.append(build_ask_user_tool())
        kwargs["tools"] = extra_tools

        # Wire interrupt_on for mutating tools so their action_requests
        # interrupts surface to the clarification relay (tool_approval origin)
        # instead of being silently auto-approved.
        # Read-only interaction modes (plan/ask) keep their own deny-based
        # permissions; agent mode gets interrupt_on for write/exec tools.
        if kwargs.get("interaction_mode") not in ("plan", "ask"):
            from langchain.agents.middleware import InterruptOnConfig

            _approve_reject = InterruptOnConfig(allowed_decisions=["approve", "reject"])
            kwargs.setdefault(
                "interrupt_on",
                {
                    "edit_file": _approve_reject,
                    "write_file": _approve_reject,
                    "delete": _approve_reject,
                    "run_command": _approve_reject,
                },
            )

        try:
            agent = super().build(*args, **kwargs)
        finally:
            self._identity_runtime = None
        from soothe.coreagent.core_agent import SootheNanoAgent

        if not isinstance(agent, SootheNanoAgent):
            agent.__class__ = SootheNanoAgent
        agent.bind_intake_only_subagents(self._intake_only_specs)
        return agent


def create_soothe_agent(config: Any | None = None, **kwargs: Any):
    """Create SootheNanoAgent with soothe host injections."""
    builder = AgentBuilder(config)
    return builder.build(**kwargs)


__all__ = ["AgentBuilder", "create_soothe_agent"]
