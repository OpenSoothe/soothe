"""Coding CoreAgent runtime surface for soothe-nano."""

from soothe_nano.agent.core_agent import CodingCoreAgent, ephemeral_execute_stream_enabled
from soothe_nano.agent.lazy import LazyCoreAgent
from soothe_nano.agent.subagent_catalog import (
    INTAKE_ONLY_WIRE_SUBAGENTS,
    is_intake_only_wire_subagent,
    partition_subagent_specs,
    spec_subagent_name,
)

__all__ = [
    "CodingCoreAgent",
    "INTAKE_ONLY_WIRE_SUBAGENTS",
    "LazyCoreAgent",
    "ephemeral_execute_stream_enabled",
    "is_intake_only_wire_subagent",
    "partition_subagent_specs",
    "spec_subagent_name",
]
