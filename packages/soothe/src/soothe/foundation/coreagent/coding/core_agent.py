"""CoreAgent class definition.

Soothe-hosted Coding CoreAgent (canonical implementation in soothe-nano).
"""

from __future__ import annotations

from typing import Any

from soothe_nano.agent.core_agent import (
    CodingCoreAgent as _NanoCodingCoreAgent,
)
from soothe_nano.agent.core_agent import (
    _normalize_layer1_input,
)


class CodingCoreAgent(_NanoCodingCoreAgent):
    """Soothe-hosted Coding CoreAgent (canonical implementation in soothe-nano)."""

    @classmethod
    def create(cls, config: Any | None = None, **kwargs: Any) -> CodingCoreAgent:
        from soothe.foundation.coreagent.coding.builder import create_soothe_agent

        return create_soothe_agent(config, **kwargs)


__all__ = ["CodingCoreAgent", "_normalize_layer1_input"]
