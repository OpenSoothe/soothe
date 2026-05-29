# Channel Architecture Evolution Design

**Status**: Draft
**Date**: 2026-05-29
**Author**: Xiaming Chen

## Summary

Evolve soothe-daemon's `TransportManager` into a unified `ChannelManager` that treats WebSocket and HTTP REST as channels (not special transports), uses EventBus for all message routing, and establishes a two-layer message system separating channel routing from agent event processing. This architecture enables integration of external chat platforms (Telegram, Discord, Matrix, Slack, WhatsApp, etc.) as first-class channels alongside existing transports.

## Motivation

Current architecture limitations:
1. **TransportManager is hardcoded**: WebSocket and HTTP REST are special cases, not extensible
2. **No plugin mechanism**: Cannot add new platforms without modifying daemon code
3. **Two message systems**: SootheEvent (agent-centric) and nanobot's InboundMessage/OutboundMessage (channel-centric) are parallel but incompatible
4. **Multi-user routing unclear**: WebSocket routes by `loop_id`, chat platforms route by `chat_id` - no unified identity model

Goals:
- Treat all communication endpoints as channels with consistent interface
- Enable plugin discovery for external channels (entry points)
- Unified routing through existing EventBus
- Clear identity model for multi-user, multi-channel support

## Architecture

### Core Abstractions

#### Channel Base Class

All communication endpoints implement a single `Channel` abstract class with capability flags:

```python
class Channel(ABC):
    """Abstract base class for all communication channels."""

    name: str                       # Identifier: "websocket", "telegram", "discord"
    display_name: str               # Human-readable: "WebSocket", "Telegram"
    supports_inbound: bool = True   # Can receive messages from platform
    supports_outbound: bool = True  # Can send messages to platform
    supports_streaming: bool = False # Can handle incremental text deltas

    @abstractmethod
    async def start(self) -> None:
        """Start channel, begin listening for messages. Blocks indefinitely."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop channel, cleanup resources."""

    @abstractmethod
    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Deliver outbound message to platform. Raises on failure."""

    # Optional streaming methods
    async def send_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream incremental text chunk. Override to enable streaming."""
        pass

    async def send_reasoning_delta(self, chat_id: str, delta: str, metadata: dict) -> None:
        """Stream reasoning/thinking content. Override for channels with low-emphasis UI."""
        pass

    # Inbound handling - calls manager directly
    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Process incoming message, call manager.handle_inbound()."""
        pass
```

Capability flags determine behavior:
- `supports_inbound=False`: HTTP REST (only receives requests, doesn't consume agent output)
- `supports_outbound=False`: One-way notification channels (webhooks)
- `supports_streaming=True`: WebSocket, Telegram (edit-in-place), Discord (message update)

#### Two-Layer Message System

Channel layer and agent layer are separate, with translation at ChannelManager boundary.

**Channel Layer** (`ChannelMessage`):
```python
@dataclass
class ChannelMessage:
    """Message for channel routing and platform delivery."""
    channel: str              # Target channel name
    chat_id: str              # Conversation/thread identifier
    content: str              # Text content (markdown)
    media: list[str]          # File paths/URLs to attach
    buttons: list[list[str]]  # Interactive buttons (optional)
    metadata: dict            # Channel-specific flags: _progress, _tool_hint, _stream_delta, _stream_end
```

**Agent Layer** (SootheEvent subclasses):
```python
class ChannelMessageReceived(ProtocolEvent):
    """Event representing user message from any channel."""
    type: str = "soothe.channel.message.received"
    channel: str              # Source channel
    chat_id: str              # Conversation identifier
    sender_id: str            # User identifier
    content: str              # Message text
    media: list[str]          # Attachments
    metadata: dict            # Channel-specific extras

class TextEvent(OutputEvent):
    """Complete text output for user display."""
    type: str = "soothe.output.text.complete"
    content: str

class TextDeltaEvent(OutputEvent):
    """Incremental text chunk for streaming."""
    type: str = "soothe.output.text.delta"
    content: str
    stream_id: str            # Unique stream identifier

class TextEndEvent(OutputEvent):
    """Marker ending a text stream."""
    type: str = "soothe.output.text.end"
    stream_id: str

class AgentUIEvent(OutputEvent):
    """Structured UI payload for rich clients."""
    type: str = "soothe.output.ui.render"
    payload: dict             # JSON-serializable UI specification
```

Only `OutputEvent` domain events are translated to `ChannelMessage` for delivery. Internal events (lifecycle, tool, subagent) stay within agent/daemon and are not sent to users.

#### ChannelManager

Evolved from `TransportManager` with additional responsibilities:

```python
class ChannelManager:
    """Coordinates all channels, handles routing and translation."""

    def __init__(self, config: SootheDaemonConfig, event_bus: EventBus, ...):
        self._event_bus = event_bus
        self._channels: dict[str, Channel] = {}
        self._loop_to_channel: dict[str, tuple[str, str]] = {}  # loop_id → (channel, chat_id)
        self._channel_to_loop: dict[tuple[str, str], str] = {}  # (channel, chat_id) → loop_id

    # Lifecycle
    async def start_all(self) -> None: ...
    async def stop_all(self) -> None: ...

    # Inbound routing
    async def handle_inbound(
        self,
        channel: str,
        chat_id: str,
        sender_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """
        Called by Channel._handle_message().
        Creates or retrieves loop_id, publishes ChannelMessageReceived to EventBus.
        Returns loop_id for caller reference.
        """

    # Outbound routing
    async def _subscribe_loops(self) -> None:
        """Subscribe to all active loop topics on EventBus."""

    async def _handle_outbound_event(self, loop_id: str, event: SootheEvent) -> None:
        """
        EventBus callback for loop topic events.
        Translates OutputEvent to ChannelMessage, dispatches to channel.
        Handles streaming: coalesces deltas, buffers for non-streaming channels.
        """

    # Streaming management
    async def _coalesce_deltas(self, channel: str, chat_id: str) -> ChannelMessage | None:
        """Merge consecutive TextDeltaEvents, return coalesced message."""

    async def _buffer_for_non_streaming(self, channel: str, chat_id: str, delta: TextDeltaEvent) -> None:
        """Buffer deltas until TextEndEvent, then send complete message."""

    # Retry policy
    async def _send_with_retry(self, channel: Channel, chat_id: str, message: ChannelMessage) -> None:
        """Exponential backoff retry (1s, 2s, 4s) on send failure."""
```

#### Loop Identity Model

All channels use loop as universal session identifier:

| Channel | Loop ID Mapping |
|---------|-----------------|
| WebSocket | Explicit `loop_id` assigned per client connection |
| Telegram | `loop_id = "telegram:{chat_id}"` (one loop per conversation) |
| Discord | `loop_id = "discord:{chat_id}"` (one loop per channel/thread) |
| Matrix | `loop_id = "matrix:{room_id}"` |
| HTTP REST | Ephemeral loop for request, or routes to existing loop by parameter |

The agent always executes within a loop context. EventBus topic `loop:{loop_id}` is the primary routing mechanism.

#### EventBus Topics

| Topic | Purpose | Publishers | Subscribers |
|-------|---------|------------|-------------|
| `loop:{loop_id}` | Agent execution context | ChannelManager (inbound), Agent (outbound) | Agent (inbound), ChannelManager (outbound) |
| `channel:{name}` | Channel-wide broadcast | ChannelManager | Channel instances |
| `channel:{name}:{chat_id}` | Specific conversation | ChannelManager | Optional fine-grained routing |
| `global` | Daemon-wide events | Server, admin commands | All clients |

### Message Flows

#### Inbound Flow

```
1. Platform receives message (e.g., Telegram user sends text)
2. TelegramChannel._handle_message(sender_id, chat_id, content) called
3. Channel calls ChannelManager.handle_inbound("telegram", chat_id, sender_id, content)
4. ChannelManager:
   - Maps (channel, chat_id) → loop_id (creates if new conversation)
   - Creates ChannelMessageReceived event
   - EventBus.publish("loop:{loop_id}", event)
5. Agent subscribed to loop topic receives event
6. Agent processes message, generates response
```

#### Outbound Flow

```
1. Agent emits OutputEvent (TextEvent or TextDeltaEvent)
2. EventBus.publish("loop:{loop_id}", event)
3. ChannelManager subscribed to loop topic receives event
4. ChannelManager:
   - Lookup loop_id → (channel_name, chat_id)
   - If OutputEvent domain: translate to ChannelMessage
   - If streaming event: check channel.supports_streaming
     - True: coalesce deltas, send to channel
     - False: buffer until TextEndEvent, send complete
   - Dispatch via Channel.send(chat_id, message)
5. Channel delivers to platform API (Telegram edit/send, WebSocket frame, etc.)
6. Retry on failure with exponential backoff
```

#### Streaming with Buffering

```
TextDeltaEvent arrives at ChannelManager:
  - Check channel.supports_streaming
  - If True:
    - Coalesce with pending deltas for same (channel, chat_id)
    - Send coalesced delta to channel.send_delta()
  - If False:
    - Append to buffer queue for (channel, chat_id)

TextEndEvent arrives:
  - If channel.supports_streaming:
    - Send final delta with _stream_end metadata
  - If False:
    - Flush buffer as single complete ChannelMessage
    - Send via channel.send()

Benefits:
- Reduces API calls for fast-generating LLMs
- Non-streaming channels (email, some webhooks) receive complete messages
- Channels with edit capability (Telegram, Discord) show live updates
```

### Channel Discovery and Registry

Plugin discovery follows nanobot's proven pattern:

```python
# soothe_daemon/channels/registry.py

def discover_channel_names() -> list[str]:
    """Scan soothe_daemon/channels/ via pkgutil for available modules. No imports."""

def load_channel_class(name: str) -> type[Channel]:
    """Import and return Channel class by module name."""

def discover_enabled(enabled_names: set[str]) -> dict[str, type[Channel]]:
    """
    Return {name: ChannelClass} for enabled channels.
    Includes built-in (pkgutil) + entry_points plugins.
    Only imports enabled channels, skips disabled.
    """
```

Entry points registration in `pyproject.toml`:
```toml
[project.entry-points."soothe.channels"]
websocket = "soothe_daemon.channels.websocket:WebSocketChannel"
http_rest = "soothe_daemon.channels.http_rest:HttpRestChannel"

# Third-party plugins register their own:
# telegram = "soothe_telegram:TelegramChannel"
# discord = "soothe_discord:DiscordChannel"
```

### Configuration Schema

Rename `transports` section to `channels`, merge existing transport config with new channel configs:

```yaml
channels:
  # Built-in channels (formerly transports)
  websocket:
    enabled: true
    host: "0.0.0.0"
    port: 8765
    tls_enabled: false
    max_frame_size: 1048576

  http_rest:
    enabled: true
    host: "0.0.0.0"
    port: 8765  # Shares WebSocket listener when both enabled
    health_endpoint: true
    autopilot_endpoint: true

  # External channels (plugins)
  telegram:
    enabled: false
    api_token: "${TELEGRAM_BOT_TOKEN}"
    allow_from: ["*"]  # Or specific user IDs
    streaming: true    # Enable edit-in-place streaming

  discord:
    enabled: false
    bot_token: "${DISCORD_BOT_TOKEN}"
    allow_from: ["*"]
    streaming: true

  # Global channel settings
  transcription_provider: "groq"  # or "openai"
  transcription_language: null
  send_progress: true      # Show progress indicators
  send_tool_hints: false   # Show tool execution hints
  show_reasoning: true     # Show model thinking (where supported)
  send_max_retries: 3      # Retry attempts for outbound
```

Environment variable pattern follows Soothe convention: `SOOTHE_CHANNELS__TELEGRAM__API_TOKEN`.

### Access Control

Channels support `allow_from` whitelist for sender permission:

```python
def is_allowed(self, sender_id: str) -> bool:
    """Check sender permission: wildcard > allowlist > deny."""
    allow_list = self.config.get("allow_from", [])
    if "*" in allow_list:
        return True
    return str(sender_id) in allow_list
```

For channels without `allow_from` configured, optional pairing system (from nanobot) can issue approval codes for DM access.

### Components

#### New Files to Create

| File | Purpose |
|------|---------|
| `soothe_daemon/channels/__init__.py` | Module entry, exports Channel, ChannelManager |
| `soothe_daemon/channels/base.py` | Channel ABC with capability flags |
| `soothe_daemon/channels/message.py` | ChannelMessage dataclass |
| `soothe_daemon/channels/events.py` | ChannelMessageReceived, OutputEvent subclasses |
| `soothe_daemon/channels/registry.py` | Discovery functions (pkgutil + entry_points) |

#### Files to Modify

| File | Changes |
|------|---------|
| `soothe_daemon/channel_manager.py` | Rename from `transport_manager.py`, add translation/routing logic |
| `soothe_daemon/channels/websocket.py` | Rename from `transports/websocket.py`, convert to Channel subclass |
| `soothe_daemon/channels/http_rest.py` | Rename from `transports/http_rest.py`, convert to Channel (supports_outbound=False) |
| `soothe_daemon/config.py` | Rename `transports` → `channels` in config schema |
| `soothe/foundation/base_events.py` | Add OutputEvent subclasses: TextEvent, TextDeltaEvent, TextEndEvent, AgentUIEvent |
| `soothe_daemon/server.py` | Update to use ChannelManager, update imports |
| `soothe_daemon/session/manager.py` | Update to work with channel-based identity model |

#### Files to Deprecate/Remove

| File | Reason |
|------|---------|
| `soothe_daemon/transports/base.py` | Replaced by `channels/base.py` (Channel ABC) |
| `soothe_daemon/transports/websocket.py` | Moved to `channels/websocket.py` |
| `soothe_daemon/transports/http_rest.py` | Moved to `channels/http_rest.py` |

### Migration Path

#### Phase 1: Core Infrastructure

1. Create `channels/base.py` with Channel ABC
2. Create `channels/message.py` with ChannelMessage
3. Create `channels/events.py` with event types
4. Create `channels/registry.py` with discovery functions
5. Rename TransportManager → ChannelManager skeleton

#### Phase 2: Convert Existing Transports

1. Convert WebSocketTransport → WebSocketChannel
2. Convert HttpRestTransport → HttpRestChannel
3. Update ChannelManager to manage converted channels
4. Update config schema: `transports` → `channels`
5. Update server.py to use ChannelManager
6. Verify existing tests pass

#### Phase 3: External Channels (Plugins)

1. Create `soothe_daemon/channels/telegram.py` (reference implementation)
2. Test plugin discovery via entry_points
3. Verify multi-channel routing works
4. Add integration tests for external channel scenarios

#### Phase 4: Streaming and Polish

1. Implement delta coalescing in ChannelManager
2. Implement buffering for non-streaming channels
3. Add retry policy with exponential backoff
4. Add access control (allow_from, optional pairing)
5. Documentation and examples

### Testing Strategy

- **Unit tests**: Channel ABC compliance, message translation, registry discovery
- **Integration tests**: Multi-channel routing, streaming coalescing, retry behavior
- **Existing tests**: All current daemon tests should pass with ChannelManager
- **Plugin tests**: Mock entry_points to test external channel loading

### Open Questions

None. All design decisions have been confirmed:
- Capability flags for channel directionality (Question 1)
- Two-layer message system with translation (Question 2, 7)
- Hybrid EventBus topics for routing (Question 3)
- Loop as universal session identifier (Question 4)
- ChannelManager intermediates outbound (Question 5)
- Direct call for inbound (Question 6)
- OutputEvent domain for user delivery (Question 7)
- Streaming flag with ChannelManager buffering (Question 8)
- Registry pattern for discovery (Question 9)
- Config: merge transports → channels (Question 10)

### References

- RFC-0013: Daemon communication protocol (existing transport architecture)
- RFC-0015: Event type naming conventions
- IG-258: EventBus lock-free publishing
- IG-408: Loop-scoped subscriptions
- Nanobot channels module: `/Users/chenxm/Workspace/nanobot/nanobot/channels/`