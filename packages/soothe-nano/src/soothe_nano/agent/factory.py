"""Factory entrypoints for coding CoreAgent runtime."""

from soothe_nano.agent.builder import create_soothe_agent

create_nano_agent = create_soothe_agent

__all__ = ["create_nano_agent", "create_soothe_agent"]
