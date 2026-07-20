"""Shared MCP utilities: naming, budgeting, and connection state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypedDict

from soothe_nano.config.models import MCPTransport

# Pattern for sanitizing: keep only a-zA-Z0-9_-
_SANITIZE_PATTERN = re.compile(r"[^a-zA-Z0-9_-]")

# Reserved prefix for MCP tools
MCP_PREFIX = "mcp__"


def _sanitize(name: str) -> str:
    """Sanitize a name for MCP tool/prompt naming."""
    return _SANITIZE_PATTERN.sub("_", name)


def build_mcp_tool_name(server: str, tool: str) -> str:
    """Build a mangled MCP tool name."""
    sanitized_server = _sanitize(server)
    sanitized_tool = _sanitize(tool)
    return f"{MCP_PREFIX}{sanitized_server}__{sanitized_tool}"


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Parse mangled name into (server, bare_tool)."""
    if not name.startswith(MCP_PREFIX):
        return None
    remainder = name[len(MCP_PREFIX) :]
    parts = remainder.split("__", 1)
    if len(parts) != 2:
        return None
    server, tool = parts
    if not server or not tool:
        return None
    return (server, tool)


def is_mcp_tool_name(name: str) -> bool:
    """Check if a name is an MCP tool name."""
    return name.startswith(MCP_PREFIX)


@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    """Descriptor for a deferred MCP tool."""

    name: str  # mangled: mcp__<server>__<tool>
    bare_name: str  # original tool name from the server
    description: str
    server: str
    is_essential: bool


class BudgetTelemetry(TypedDict):
    included_count: int
    truncated_count: int
    mode: str  # "full" | "truncated" | "names_only"
    budget_chars: int
    actual_chars: int


def _is_essential(entry: MCPToolDescriptor) -> bool:
    return entry.is_essential


def _format_entry(entry: MCPToolDescriptor, *, cap: int | None) -> str:
    name = entry.name
    desc = entry.description or ""
    if cap is not None and len(desc) > cap:
        desc = desc[: max(0, cap - 1)].rstrip() + "…"
    return f"- {name}: {desc}"


def format_mcp_tools_within_budget(
    entries: list[MCPToolDescriptor],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format MCP tool listing within a character budget."""
    if not entries:
        return "", BudgetTelemetry(
            included_count=0,
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=0,
        )

    full_rendered = [_format_entry(entry, cap=None) for entry in entries]
    total_full = sum(len(rendered) + 1 for rendered in full_rendered)
    if total_full <= budget_chars:
        text = "\n".join(full_rendered)
        return text, BudgetTelemetry(
            included_count=len(entries),
            truncated_count=0,
            mode="full",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    essential = [entry for entry in entries if _is_essential(entry)]
    others = [entry for entry in entries if not _is_essential(entry)]
    essential_text = "\n".join(_format_entry(entry, cap=None) for entry in essential)
    used = len(essential_text) + 1
    remaining = max(0, budget_chars - used)
    raw_quota = (remaining // max(1, len(others))) if others else 0
    quota = min(raw_quota, per_entry_cap_chars)

    if quota < min_per_entry_chars and others:
        names = "\n".join(f"- {entry.name}" for entry in others)
        text = (essential_text + "\n" + names) if essential_text else names
        return text, BudgetTelemetry(
            included_count=len(entries),
            truncated_count=len(others),
            mode="names_only",
            budget_chars=budget_chars,
            actual_chars=len(text),
        )

    others_text = "\n".join(_format_entry(entry, cap=quota) for entry in others)
    text = (
        (essential_text + ("\n" + others_text if others_text else ""))
        if essential_text
        else others_text
    )
    return text, BudgetTelemetry(
        included_count=len(entries),
        truncated_count=sum(1 for entry in others if len(entry.description) > quota),
        mode="truncated",
        budget_chars=budget_chars,
        actual_chars=len(text),
    )


@dataclass
class MCPConnection:
    """Per-server connection state."""

    name: str
    transport: MCPTransport
    status: str = "disconnected"
    last_error: str | None = None
    reconnect_attempt: int = 0
    tool_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    connected_at: datetime | None = None
    _session: Any = field(default=None, repr=False)
