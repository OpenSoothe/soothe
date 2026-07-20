"""MCP event definitions and emitters."""

from __future__ import annotations

import logging

from soothe_sdk.core.events import SootheEvent

from soothe_nano.events.catalog import register_event

logger = logging.getLogger(__name__)

__all__ = [
    "MCPServerConnectedEvent",
    "MCPServerDisconnectedEvent",
    "MCPServerReconnectingEvent",
    "MCPServerConnectFailedEvent",
    "MCPListChangedEvent",
    "MCPToolInvokedEvent",
    "MCPToolTimeoutEvent",
    "MCPResourceReadEvent",
    "MCPPromptInvokedEvent",
    "MCPToolSearchQueriedEvent",
    "emit_server_connected",
    "emit_server_disconnected",
    "emit_server_reconnecting",
    "emit_server_connect_failed",
    "emit_list_changed",
    "emit_tool_invoked",
    "emit_tool_timeout",
    "emit_resource_read",
    "emit_prompt_invoked",
    "emit_tool_search_queried",
]

EVENT_SERVER_CONNECTED = "soothe.mcp.server.connected"
EVENT_SERVER_DISCONNECTED = "soothe.mcp.server.disconnected"
EVENT_SERVER_RECONNECTING = "soothe.mcp.server.reconnecting"
EVENT_SERVER_CONNECT_FAILED = "soothe.mcp.server.connect_failed"
EVENT_LIST_CHANGED = "soothe.internal.mcp.list_changed"
EVENT_TOOL_INVOKED = "soothe.mcp.tool.invoked"
EVENT_TOOL_TIMEOUT = "soothe.internal.mcp.tool.timeout"
EVENT_RESOURCE_READ = "soothe.mcp.resource.read"
EVENT_PROMPT_INVOKED = "soothe.mcp.prompt.invoked"
EVENT_TOOL_SEARCH_QUERIED = "soothe.mcp.tool_search.queried"


class MCPServerConnectedEvent(SootheEvent):
    type: str = EVENT_SERVER_CONNECTED
    server: str
    transport: str
    tool_count: int
    prompt_count: int
    resource_count: int
    latency_ms: float


class MCPServerDisconnectedEvent(SootheEvent):
    type: str = EVENT_SERVER_DISCONNECTED
    server: str
    reason: str
    was_clean: bool


class MCPServerReconnectingEvent(SootheEvent):
    type: str = EVENT_SERVER_RECONNECTING
    server: str
    attempt: int
    backoff_s: float


class MCPServerConnectFailedEvent(SootheEvent):
    type: str = EVENT_SERVER_CONNECT_FAILED
    server: str
    transport: str
    error_class: str
    attempt: int
    is_terminal: bool


class MCPListChangedEvent(SootheEvent):
    type: str = EVENT_LIST_CHANGED
    server: str
    kind: str
    old_count: int
    new_count: int


class MCPToolInvokedEvent(SootheEvent):
    type: str = EVENT_TOOL_INVOKED
    server: str
    tool: str
    latency_ms: float
    success: bool
    result_chars: int


class MCPToolTimeoutEvent(SootheEvent):
    type: str = EVENT_TOOL_TIMEOUT
    server: str
    tool: str
    timeout_s: float


class MCPResourceReadEvent(SootheEvent):
    type: str = EVENT_RESOURCE_READ
    server: str
    uri: str
    chars: int
    latency_ms: float


class MCPPromptInvokedEvent(SootheEvent):
    type: str = EVENT_PROMPT_INVOKED
    server: str
    prompt: str
    latency_ms: float


class MCPToolSearchQueriedEvent(SootheEvent):
    type: str = EVENT_TOOL_SEARCH_QUERIED
    query: str
    match_count: int


_internal_subscribers: list = []


def _register_events() -> None:
    """Register all MCP events with the core event catalog."""
    try:
        register_event(
            MCPServerConnectedEvent,
            summary_template="MCP {server} connected ({tool_count} tools, {latency_ms:.0f}ms)",
        )
        register_event(
            MCPServerDisconnectedEvent,
            summary_template="MCP {server} disconnected ({reason})",
        )
        register_event(
            MCPServerReconnectingEvent,
            summary_template="MCP {server} reconnecting (attempt {attempt})",
        )
        register_event(
            MCPServerConnectFailedEvent,
            summary_template="MCP {server} connect failed ({error_class})",
        )
        register_event(
            MCPListChangedEvent,
            summary_template="MCP {server} {kind} changed ({old_count} -> {new_count})",
        )
        register_event(
            MCPToolInvokedEvent,
            summary_template="MCP tool {tool} invoked ({latency_ms:.0f}ms)",
        )
        register_event(
            MCPToolTimeoutEvent,
            summary_template="MCP tool {tool} timeout ({timeout_s}s)",
        )
        register_event(
            MCPResourceReadEvent,
            summary_template="MCP resource {uri} read ({chars} chars)",
        )
        register_event(
            MCPPromptInvokedEvent,
            summary_template="MCP prompt {prompt} invoked ({latency_ms:.0f}ms)",
        )
        register_event(
            MCPToolSearchQueriedEvent,
            summary_template="MCP tool search '{query}' ({match_count} matches)",
        )
        logger.debug("[MCP] Events registered with core catalog")
    except ImportError:
        logger.warning("[MCP] Could not register events (core catalog not available)")


_register_events()


def emit_server_connected(
    server: str,
    transport: str,
    tool_count: int,
    prompt_count: int,
    resource_count: int,
    latency_ms: float,
) -> MCPServerConnectedEvent:
    event = MCPServerConnectedEvent(
        server=server,
        transport=transport,
        tool_count=tool_count,
        prompt_count=prompt_count,
        resource_count=resource_count,
        latency_ms=latency_ms,
    )
    _emit_internal(event)
    return event


def emit_server_disconnected(
    server: str,
    reason: str,
    was_clean: bool,
) -> MCPServerDisconnectedEvent:
    event = MCPServerDisconnectedEvent(server=server, reason=reason, was_clean=was_clean)
    _emit_internal(event)
    return event


def emit_server_reconnecting(
    server: str,
    attempt: int,
    backoff_s: float,
) -> MCPServerReconnectingEvent:
    event = MCPServerReconnectingEvent(server=server, attempt=attempt, backoff_s=backoff_s)
    _emit_internal(event)
    return event


def emit_server_connect_failed(
    server: str,
    transport: str,
    error_class: str,
    attempt: int,
    is_terminal: bool,
) -> MCPServerConnectFailedEvent:
    event = MCPServerConnectFailedEvent(
        server=server,
        transport=transport,
        error_class=error_class,
        attempt=attempt,
        is_terminal=is_terminal,
    )
    _emit_internal(event)
    return event


def emit_list_changed(
    server: str,
    kind: str,
    old_count: int,
    new_count: int,
) -> MCPListChangedEvent:
    event = MCPListChangedEvent(server=server, kind=kind, old_count=old_count, new_count=new_count)
    _emit_internal(event)
    return event


def emit_tool_invoked(
    server: str,
    tool: str,
    latency_ms: float,
    success: bool,
    result_chars: int,
) -> MCPToolInvokedEvent:
    event = MCPToolInvokedEvent(
        server=server,
        tool=tool,
        latency_ms=latency_ms,
        success=success,
        result_chars=result_chars,
    )
    _emit_internal(event)
    return event


def emit_tool_timeout(
    server: str,
    tool: str,
    timeout_s: float,
) -> MCPToolTimeoutEvent:
    event = MCPToolTimeoutEvent(server=server, tool=tool, timeout_s=timeout_s)
    _emit_internal(event)
    return event


def emit_resource_read(
    server: str,
    uri: str,
    chars: int,
    latency_ms: float,
) -> MCPResourceReadEvent:
    event = MCPResourceReadEvent(server=server, uri=uri, chars=chars, latency_ms=latency_ms)
    _emit_internal(event)
    return event


def emit_prompt_invoked(
    server: str,
    prompt: str,
    latency_ms: float,
) -> MCPPromptInvokedEvent:
    event = MCPPromptInvokedEvent(server=server, prompt=prompt, latency_ms=latency_ms)
    _emit_internal(event)
    return event


def emit_tool_search_queried(
    query: str,
    match_count: int,
) -> MCPToolSearchQueriedEvent:
    event = MCPToolSearchQueriedEvent(query=query, match_count=match_count)
    _emit_internal(event)
    return event


def _emit_internal(event: object) -> None:
    """Emit event to internal subscribers."""
    for subscriber in _internal_subscribers:
        try:
            subscriber(event)
        except Exception as error:
            logger.warning("[MCP] Event subscriber error: %s", error)
