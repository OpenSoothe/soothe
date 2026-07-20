"""MCPConnection dataclass for per-server state (RFC-412)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from soothe_nano.config.models import MCPTransport


@dataclass
class MCPConnection:
    """Per-server connection state (RFC-412).

    Tracks status, errors, reconnect attempts, and capability counts.
    """

    name: str
    transport: MCPTransport
    status: str = "disconnected"  # "connected" | "disconnected" | "reconnecting" | "connect_failed" | "connect_failed_terminal"
    last_error: str | None = None
    reconnect_attempt: int = 0
    tool_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    connected_at: datetime | None = None
    # Reference to underlying session (langchain_mcp_adapters session)
    _session: Any = field(default=None, repr=False)
