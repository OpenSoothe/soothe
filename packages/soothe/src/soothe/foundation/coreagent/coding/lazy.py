"""Lazy CoreAgent wrapper (IG-506).

Host subclass forwards intake-only registry access after materialization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from soothe_nano.agent.lazy import LazyCoreAgent as _NanoLazyCoreAgent
from soothe_nano.agent.lazy import MaterializeHook

if TYPE_CHECKING:
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent


class LazyCoreAgent(_NanoLazyCoreAgent):
    """Lazy wrapper that exposes host intake-only specialist lookup."""

    @property
    def intake_only_subagents(self) -> list[SubAgent | CompiledSubAgent]:
        agent = self.materialize()
        return list(getattr(agent, "intake_only_subagents", []))

    def lookup_intake_only_subagent(self, name: str) -> SubAgent | CompiledSubAgent | None:
        agent = self.materialize()
        lookup = getattr(agent, "lookup_intake_only_subagent", None)
        return lookup(name) if callable(lookup) else None


__all__ = ["LazyCoreAgent", "MaterializeHook"]
