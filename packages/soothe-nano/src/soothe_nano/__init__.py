"""soothe-nano — batteries-included Coding CoreAgent (no StrangeLoop/Autopilot)."""

from __future__ import annotations

import importlib.metadata

from soothe_sdk.protocols.core_agent import CoreAgentCapabilities

from soothe_nano.agent import CodingCoreAgent, LazyCoreAgent
from soothe_nano.agent.execute_stream import ephemeral_execute_stream_enabled
from soothe_nano.agent.factory import create_nano_agent
from soothe_nano.agent.subagent_catalog import (
    INTAKE_ONLY_WIRE_SUBAGENTS,
    partition_subagent_specs,
    spec_subagent_name,
)
from soothe_nano.config import SootheConfig

try:
    NanoConfig = SootheConfig
except Exception:  # pragma: no cover
    NanoConfig = None  # type: ignore[misc, assignment]

try:
    __version__ = importlib.metadata.version("soothe-nano")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "CodingCoreAgent",
    "CoreAgentCapabilities",
    "INTAKE_ONLY_WIRE_SUBAGENTS",
    "LazyCoreAgent",
    "NanoConfig",
    "SootheConfig",
    "create_nano_agent",
    "ephemeral_execute_stream_enabled",
    "partition_subagent_specs",
    "spec_subagent_name",
    "__version__",
]
