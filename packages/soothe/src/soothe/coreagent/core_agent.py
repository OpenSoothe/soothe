"""Soothe-hosted Coding CoreAgent (canonical implementation in soothe-nano)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Re-export facade — canonical source: soothe_nano.agent.core_agent
from soothe_nano.agent import core_agent as nano_core_agent

from soothe.sloop.subagent_catalog import lookup_subagent_spec

if TYPE_CHECKING:
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent


_normalize_layer1_input = nano_core_agent._normalize_layer1_input


class CodingCoreAgent(nano_core_agent.CodingCoreAgent):
    """Soothe-hosted Coding CoreAgent with intake-only specialist registry."""

    def bind_intake_only_subagents(self, specs: list[SubAgent | CompiledSubAgent] | None) -> None:
        """Attach specialists withheld from the open ``task`` catalog (host wiring)."""
        self._intake_only_subagents = list(specs) if specs else []

    @property
    def intake_only_subagents(self) -> list[SubAgent | CompiledSubAgent]:
        """Intake-only specialists (not on the open ``task`` catalog)."""
        return list(getattr(self, "_intake_only_subagents", []))

    def lookup_intake_only_subagent(self, name: str) -> SubAgent | CompiledSubAgent | None:
        """Return an intake-only CompiledSubAgent/SubAgent spec by name."""
        return lookup_subagent_spec(self.intake_only_subagents, name)

    @classmethod
    def create(cls, config: Any | None = None, **kwargs: Any) -> CodingCoreAgent:
        from soothe.coreagent.builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)


__all__ = ["CodingCoreAgent", "_normalize_layer1_input"]
