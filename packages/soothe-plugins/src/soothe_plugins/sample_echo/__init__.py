"""Sample echo subagent — minimal community plugin for Soothe integration tests."""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .implementation import create_echo_subagent_spec

__all__ = ["SampleEchoPlugin", "create_echo_subagent_spec"]

logger = logging.getLogger(__name__)


@plugin(
    name="sample_echo",
    version="1.0.0",
    description="Minimal echo subagent for testing soothe-plugins against the Soothe daemon",
    dependencies=["langgraph>=0.2.0"],
    trust_level="standard",
)
class SampleEchoPlugin:
    """Registers a no-LLM subgraph so CI can validate plugin subagent loading."""

    async def on_load(self, context: Any) -> None:
        """No-op load hook."""
        context.logger.info("sample_echo plugin loaded")

    @subagent(
        name="sample_echo",
        description=("Echoes the user's last message with a sample_echo tag. For automated tests only."),
    )
    async def create_sample_echo(
        self,
        model: Any,
        config: Any,
        context: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Materialize the echo subgraph (model and global config unused)."""
        _ = model, config, context
        return create_echo_subagent_spec()
