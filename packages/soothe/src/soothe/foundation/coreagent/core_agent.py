"""Soothe-hosted Coding CoreAgent (canonical implementation in soothe-nano)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from soothe_nano.agent.core_agent import CodingCoreAgent as _NanoCodingCoreAgent
from soothe_nano.agent.core_agent import _normalize_layer1_input

from soothe.foundation.sloop.subagent_catalog import lookup_subagent_spec

if TYPE_CHECKING:
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent


class CodingCoreAgent(_NanoCodingCoreAgent):
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
        from soothe.foundation.coreagent.builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)


__all__ = ["CodingCoreAgent", "_normalize_layer1_input"]
