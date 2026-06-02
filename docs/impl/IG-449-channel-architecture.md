# IG-449: Unified Channel Architecture Implementation

**IG**: 449
**Title**: Unified Channel Architecture Implementation
**RFC**: RFC-620
**Status**: Completed
**Created**: 2026-05-29
**Author**: Xiaming Chen

## Overview

Implement RFC-620: Evolve `TransportManager` into `ChannelManager`, convert WebSocket and HTTP REST to Channel subclasses, establish two-layer message system, add plugin discovery.

## Scope

| Phase | Scope | Files |
|-------|-------|-------|
| 1 | Core infrastructure (Channel ABC, messages, events, registry) | ~5 new files |
| 2 | Convert existing transports to channels | ~5 files modified |
| 3 | External channels (Telegram reference) | ~1 new file + tests |
| 4 | Streaming and polish | Tests, documentation |

## Implementation Plan

### Phase 1: Core Infrastructure

#### Task 1.1: Create Channel ABC

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/base.py`

```python
"""Channel base class (RFC-620 §1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_daemon.channels.message import ChannelMessage

class Channel(ABC):
    """Abstract base class for all communication channels."""

    name: str = "base"
    display_name: str = "Base"
    supports_inbound: bool = True
    supports_outbound: bool = True
    supports_streaming: bool = False

    def __init__(self, config: Any, manager: Any) -> None:
        self.config = config
        self._manager = manager
        self._running = False

    @abstractmethod
    async def start(self) -> None:
        """Start channel, begin listening. Blocks indefinitely."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop channel, cleanup resources."""

    @abstractmethod
    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message. Raises on failure."""

    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream incremental text chunk. Optional override."""
        pass

    async def send_reasoning_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream reasoning/thinking. Optional override."""
        pass

    @property
    def is_running(self) -> bool:
        return self._running

    def is_allowed(self, sender_id: str) -> bool:
        """Check sender permission via allow_from whitelist."""
        allow_list = self._get_allow_list()
        if "*" in allow_list:
            return True
        return str(sender_id) in allow_list

    def _get_allow_list(self) -> list[str]:
        if isinstance(self.config, dict):
            return self.config.get("allow_from", [])
        return getattr(self.config, "allow_from", [])
```

#### Task 1.2: Create ChannelMessage

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/message.py`

```python
"""Channel message types (RFC-620 §2.1)."""

from dataclasses import dataclass, field
from typing import Any

@dataclass
class ChannelMessage:
    """Message for channel routing and platform delivery."""
    channel: str
    chat_id: str
    content: str
    media: list[str] = field(default_factory=list)
    buttons: list[list[str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

#### Task 1.3: Create Channel Events

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/events.py`

```python
"""Channel event types (RFC-620 §2.2)."""

from soothe.foundation.base_events import ProtocolEvent, OutputEvent

class ChannelMessageReceived(ProtocolEvent):
    """User message from any channel."""
    type: str = "soothe.channel.message.received"
    channel: str
    chat_id: str
    sender_id: str
    content: str
    media: list[str] = []
    metadata: dict = {}

class TextEvent(OutputEvent):
    """Complete text output."""
    type: str = "soothe.output.text.complete"
    content: str

class TextDeltaEvent(OutputEvent):
    """Incremental text chunk."""
    type: str = "soothe.output.text.delta"
    content: str
    stream_id: str

class TextEndEvent(OutputEvent):
    """End text stream marker."""
    type: str = "soothe.output.text.end"
    stream_id: str
```

#### Task 1.4: Create Registry

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/registry.py`

```python
"""Channel discovery registry (RFC-620 §7)."""

import importlib
import pkgutil
from typing import type

from soothe_daemon.channels.base import Channel

def discover_channel_names() -> list[str]:
    """Scan channels/ directory via pkgutil. No imports."""
    from soothe_daemon.channels import __path__
    names = []
    for info in pkgutil.iter_modules(__path__):
        if info.name not in ("base", "message", "events", "registry", "__init__"):
            names.append(info.name)
    return names

def load_channel_class(name: str) -> type[Channel] | None:
    """Import and return Channel class by module name."""
    try:
        module = importlib.import_module(f"soothe_daemon.channels.{name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and issubclass(attr, Channel) and attr is not Channel:
                return attr
    except ImportError:
        pass
    return None

def discover_plugins(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """Load external channels via entry_points."""
    channels = {}
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group="soothe.channels")
        for ep in eps:
            if ep.name in enabled_names:
                cls = ep.load()
                if isinstance(cls, type) and issubclass(cls, Channel):
                    channels[ep.name] = cls
    except Exception:
        pass
    return channels

def discover_enabled(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """Return {name: ChannelClass} for enabled channels."""
    channels = {}
    # Built-in from pkgutil
    for name in enabled_names:
        cls = load_channel_class(name)
        if cls:
            channels[name] = cls
    # Plugins from entry_points
    channels.update(discover_plugins(enabled_names))
    return channels
```

#### Task 1.5: Create Package Init

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/__init__.py`

```python
"""Channel module (RFC-620)."""

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.registry import discover_channel_names, discover_enabled

__all__ = [
    "Channel",
    "ChannelMessage",
    "discover_channel_names",
    "discover_enabled",
]
```

### Phase 2: Convert Existing Transports

#### Task 2.1: Create ChannelManager

**File**: `packages/soothe-daemon/src/soothe_daemon/channel_manager.py`

Rename from `transport_manager.py`, add translation logic:

Key additions:
- `_loop_to_channel: dict[str, tuple[str, str]]` mapping
- `_channel_to_loop: dict[tuple[str, str], str]` reverse mapping
- `handle_inbound(channel, chat_id, sender_id, content, ...)` method
- `_handle_outbound_event(loop_id, event)` EventBus callback
- `_subscribe_to_loop(loop_id)` and `_unsubscribe_from_loop(loop_id)`
- `_coalesce_deltas()` for streaming
- `_buffer_for_non_streaming()` for buffering
- `_send_with_retry()` exponential backoff

#### Task 2.2: Convert WebSocketTransport → WebSocketChannel

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/websocket.py`

Changes from current `transports/websocket.py`:
- Inherit from `Channel` instead of `TransportServer`
- Set `supports_streaming = True`
- `chat_id` maps to client's subscribed `loop_id`
- Implement `send_delta()` for streaming frames

#### Task 2.3: Convert HttpRestTransport → HttpRestChannel

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/http_rest.py`

Changes:
- Inherit from `Channel`
- Set `supports_outbound = False` (HTTP REST doesn't push to clients)
- Keep health check, autopilot endpoints

#### Task 2.4: Update Config

**File**: `packages/soothe-daemon/src/soothe_daemon/config.py`

Rename `TransportsConfig` → `ChannelsConfig`:
```python
class ChannelsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")  # Allow per-channel sections

    websocket: WebSocketChannelConfig = WebSocketChannelConfig()
    http_rest: HttpRestChannelConfig = HttpRestChannelConfig()

    # Global channel settings
    transcription_provider: str = "groq"
    send_progress: bool = True
    send_tool_hints: bool = False
    show_reasoning: bool = True
    send_max_retries: int = 3
```

#### Task 2.5: Update Server

**File**: `packages/soothe-daemon/src/soothe_daemon/server.py`

Replace `TransportManager` imports with `ChannelManager`.

### Phase 3: External Channels

#### Task 3.1: Telegram Channel Reference

**File**: `packages/soothe-daemon/src/soothe_daemon/channels/telegram.py`

Reference implementation showing plugin pattern:
- `name = "telegram"`
- `supports_streaming = True` (via message edit)
- `send_delta()` uses editMessageText API
- `_handle_message()` calls `manager.handle_inbound()`

### Phase 4: Streaming and Polish

#### Task 4.1: Delta Coalescing

In ChannelManager, implement `_coalesce_stream_deltas()` per nanobot pattern:
- Merge consecutive `TextDeltaEvent` for same `(channel, chat_id)`
- Accumulate content until `TextEndEvent`
- Send coalesced delta to reduce API calls

#### Task 4.2: Buffering for Non-Streaming

- Queue deltas in `_stream_buffer: dict[tuple[str, str], list[TextDeltaEvent]]`
- On `TextEndEvent`, flush as single `ChannelMessage`

#### Task 4.3: Tests

- `tests/unit/channels/test_base.py`: Channel ABC compliance
- `tests/unit/channels/test_registry.py`: Discovery functions
- `tests/unit/channels/test_message.py`: Message types
- `tests/integration/test_channel_routing.py`: Multi-channel routing

#### Task 4.4: Documentation

- Plugin guide: How to create a new channel
- Config reference: `channels.*` settings

## Dependencies

- soothe.foundation.base_events (ProtocolEvent, OutputEvent)
- soothe_daemon.event.bus (EventBus)
- soothe_daemon.session.manager (ClientSessionManager - unchanged)

## Verification

Run `./scripts/verify_finally.sh` after each phase:
- Phase 1: Lint passes, imports work
- Phase 2: All existing daemon tests pass
- Phase 3: Integration tests pass
- Phase 4: Full verification suite passes

## Status Tracking

| Task | Status |
|------|--------|
| 1.1 Channel ABC | ✅ Complete |
| 1.2 ChannelMessage | ✅ Complete |
| 1.3 Channel Events | ✅ Complete |
| 1.4 Registry | ✅ Complete |
| 1.5 Package Init | ✅ Complete |
| 2.1 ChannelManager | ✅ Complete |
| 2.2 WebSocketChannel | ✅ Complete |
| 2.3 HttpRestChannel | ✅ Complete |
| 2.4 Config | ✅ Complete |
| 2.5 Server | ✅ Complete |
| 2.6 Remove transports/ module | ✅ Complete |
| 3.1 Telegram | Pending (external plugin) |
| 4.1 Coalescing | ✅ Complete |
| 4.2 Buffering | ✅ Complete |
| 4.3 Tests | ✅ Complete (143 tests) |
| 4.4 Docs | ✅ Complete |

## References

- RFC-620: Unified Channel Architecture
- RFC-450: Daemon communication protocol (current transport architecture)
- Nanobot channels module: `/Users/chenxm/Workspace/nanobot/nanobot/channels/`