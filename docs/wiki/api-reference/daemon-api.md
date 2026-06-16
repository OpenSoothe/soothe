# Daemon API Reference

The Soothe Daemon package (`soothe_daemon`) provides the background agent runner with WebSocket IPC and multi-transport communication.

**Package**: `soothe-daemon`  
**Import**: `from soothe_daemon import ...`  
**Python**: `>=3.11`

---

## Table of Contents

1. [Server Lifecycle](#server-lifecycle)
2. [Bootstrap Entrypoint](#bootstrap-entrypoint)
3. [Channel Management](#channel-management)
4. [Health Checks](#health-checks)
5. [RPC Commands](#rpc-commands)

---

## Server Lifecycle

### SootheDaemon

**Import**: `from soothe_daemon import SootheDaemon`

Main daemon server class managing the agent runtime and communication channels.

#### Constructor

```python
SootheDaemon(
    config: SootheConfig | None = None,
    *,
    transports: list[str] | None = None,
    enable_autopilot: bool = False,
)
```

**Parameters**:
- `config`: Soothe configuration
- `transports`: List of transport types to enable (`["websocket", "http_rest"]`)
- `enable_autopilot`: Enable autopilot autonomous goal execution

**Example**:
```python
from soothe_daemon import SootheDaemon
from soothe.config import SootheConfig

# Create daemon with configuration
config = SootheConfig.from_yaml("config/config.yml")

daemon = SootheDaemon(
    config=config,
    transports=["websocket", "http_rest"],
    enable_autopilot=True,
)
```

#### Methods

##### `start()`

```python
async def start() -> None
```

Start the daemon and all configured transports.

**Raises**:
- `RuntimeError`: If daemon fails to initialize

**Example**:
```python
import asyncio

async def run_daemon():
    daemon = SootheDaemon()
    await daemon.start()
    print("Daemon started")
    
    # Keep running
    try:
        await asyncio.Future()  # Run forever
    finally:
        await daemon.stop()

asyncio.run(run_daemon())
```

##### `stop()`

```python
async def stop() -> None
```

Stop the daemon and cleanup resources.

**Example**:
```python
daemon = SootheDaemon()
await daemon.start()

# ... use daemon ...

await daemon.stop()
print("Daemon stopped")
```

##### `wait_ready()`

```python
async def wait_ready(timeout: float = 30.0) -> None
```

Wait for daemon to be fully ready.

**Parameters**:
- `timeout`: Maximum wait time in seconds

**Raises**:
- `TimeoutError`: If daemon doesn't become ready within timeout

**Example**:
```python
daemon = SootheDaemon()
await daemon.start()

# Wait for readiness
await daemon.wait_ready(timeout=10.0)
print("Daemon ready to accept connections")
```

##### `status()`

```python
def status() -> dict[str, Any]
```

Get daemon status dictionary.

**Returns**: Status dictionary with structure:
```python
{
    "state": "ready" | "starting" | "warming" | "error",
    "uptime_seconds": 123.45,
    "active_connections": 3,
    "active_loops": 2,
    "transports": {
        "websocket": {"enabled": True, "client_count": 3},
        "http_rest": {"enabled": True}
    },
    "autopilot": {
        "enabled": True,
        "dreaming": False,
        "active_goals": 2
    }
}
```

**Example**:
```python
status = daemon.status()
print(f"Daemon state: {status['state']}")
print(f"Active connections: {status['active_connections']}")
```

---

### DaemonProcess

**Import**: `from soothe_daemon.server.process import DaemonProcess`

Process-level daemon management for background operation.

#### Constructor

```python
DaemonProcess(
    config_path: str | None = None,
    pid_file: str | None = None,
)
```

**Parameters**:
- `config_path`: Path to configuration file
- `pid_file`: Path to PID file for process tracking

**Methods**:

##### `spawn()`

```python
async def spawn() -> int
```

Spawn daemon as background process.

**Returns**: Process ID

**Example**:
```python
from soothe_daemon.server.process import DaemonProcess

process = DaemonProcess(
    config_path="config/config.yml",
    pid_file="/tmp/soothe.pid"
)

pid = await process.spawn()
print(f"Daemon started with PID {pid}")
```

##### `kill()`

```python
async def kill() -> None
```

Kill the daemon process.

**Example**:
```python
process = DaemonProcess()
await process.kill()
print("Daemon process killed")
```

##### `is_alive()`

```python
def is_alive() -> bool
```

Check if daemon process is running.

**Example**:
```python
if process.is_alive():
    print("Daemon is running")
else:
    print("Daemon is stopped")
```

---

## Bootstrap Entrypoint

### run_daemon()

**Import**: `from soothe_daemon.bootstrap import run_daemon`

Main entrypoint for running the daemon.

#### Signature

```python
async def run_daemon(
    config_path: str | None = None,
    *,
    transports: list[str] = ["websocket"],
    enable_autopilot: bool = False,
    daemon_mode: bool = False,
) -> None
```

**Parameters**:
- `config_path`: Path to configuration YAML file
- `transports`: List of transport types
- `enable_autopilot`: Enable autopilot mode
- `daemon_mode`: Run as background daemon process

**Example**:
```python
import asyncio
from soothe_daemon.bootstrap import run_daemon

# Run daemon in foreground
asyncio.run(run_daemon(
    config_path="config/config.yml",
    transports=["websocket", "http_rest"],
    enable_autopilot=True,
))
```

---

### pid_path()

**Import**: `from soothe_daemon.bootstrap import pid_path`

Get the PID file path for daemon process tracking.

#### Signature

```python
def pid_path() -> Path
```

**Returns**: Path to PID file (default: `${SOOTHE_HOME}/soothe.pid`)

**Example**:
```python
from soothe_daemon.bootstrap import pid_path
from pathlib import Path

pid_file = pid_path()
print(f"PID file: {pid_file}")

# Check if daemon is running
if pid_file.exists():
    pid = int(pid_file.read_text().strip())
    print(f"Daemon running with PID {pid}")
```

---

## Channel Management

### ChannelManager

**Import**: `from soothe_daemon.channel_manager import ChannelManager`

Manager for multi-transport communication channels.

#### Constructor

```python
ChannelManager(
    *,
    message_handler: Callable[[str, dict], None] | None = None,
)
```

**Parameters**:
- `message_handler`: Callback for inbound messages

**Methods**:

##### `register_channel()`

```python
async def register_channel(
    channel: Channel,
    *,
    runner: SootheRunner | None = None,
    config: SootheConfig | None = None,
) -> None
```

Register a communication channel.

**Parameters**:
- `channel`: Channel instance (WebSocket, HTTP REST, etc.)
- `runner`: Optional SootheRunner for agent execution
- `config`: Optional SootheConfig

**Example**:
```python
from soothe_daemon.channel_manager import ChannelManager
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.channels.http_rest import HttpRestChannel

manager = ChannelManager()

# Register WebSocket channel
ws_channel = WebSocketChannel(config.ws_config, manager)
await manager.register_channel(ws_channel, runner=my_runner)

# Register HTTP REST channel
http_channel = HttpRestChannel(config.http_config, manager)
await manager.register_channel(http_channel, runner=my_runner)
```

##### `broadcast()`

```python
async def broadcast(
    message: dict[str, Any],
    *,
    exclude_clients: list[str] | None = None,
) -> None
```

Broadcast message to all connected clients.

**Parameters**:
- `message`: Message dictionary
- `exclude_clients`: Optional list of client IDs to exclude

**Example**:
```python
# Broadcast daemon status update
await manager.broadcast({
    "type": "daemon_status",
    "data": daemon.status()
})
```

##### `send_to_client()`

```python
async def send_to_client(
    client_id: str,
    message: dict[str, Any],
) -> None
```

Send message to specific client.

**Parameters**:
- `client_id`: Client identifier
- `message`: Message dictionary

**Example**:
```python
await manager.send_to_client("client-123", {
    "type": "command_response",
    "data": {"status": "success"}
})
```

---

### Channel (Base Class)

**Import**: `from soothe_daemon.channels.base import Channel`

Base class for communication channels.

#### Definition

```python
class Channel(ABC):
    """Abstract base class for communication channels."""
    
    name: str
    """Channel name identifier."""
    
    display_name: str
    """Human-readable channel name."""
    
    supports_inbound: bool
    """Whether channel supports inbound messages."""
    
    supports_outbound: bool
    """Whether channel supports outbound messages."""
    
    supports_streaming: bool
    """Whether channel supports streaming."""
    
    def __init__(self, config: Any, manager: ChannelManager):
        """Initialize channel with config and manager."""
        ...
    
    @abstractmethod
    async def start(self) -> None:
        """Start the channel."""
        ...
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the channel."""
        ...
    
    @abstractmethod
    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send message to specific chat/client."""
        ...
    
    @abstractmethod
    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast message to all clients."""
        ...
    
    @property
    def client_count(self) -> int:
        """Get number of connected clients."""
        ...
    
    @property
    def running(self) -> bool:
        """Check if channel is running."""
        ...
```

---

### WebSocketChannel

**Import**: `from soothe_daemon.channels.websocket import WebSocketChannel`

WebSocket transport for bidirectional streaming communication.

#### Constructor

```python
WebSocketChannel(
    config: WebSocketConfig,
    manager: ChannelManager,
    *,
    runner: SootheRunner | None = None,
    soothe_config: SootheConfig | None = None,
    session_manager: ClientSessionManager | None = None,
)
```

**Configuration**:
```yaml
transport:
  websocket:
    enabled: true
    host: localhost
    port: 8765
    max_frame_size: 10485760  # 10 MiB
    ping_interval: 30
    ping_timeout: 60
```

**Example**:
```python
from soothe_daemon.channels.websocket import WebSocketChannel
from soothe_daemon.config.models import WebSocketConfig

ws_config = WebSocketConfig(
    host="localhost",
    port=8765,
    max_frame_size=10 * 1024 * 1024,
)

ws_channel = WebSocketChannel(
    ws_config,
    manager,
    runner=my_runner,
    soothe_config=config,
)

await ws_channel.start()
print(f"WebSocket listening on ws://{ws_config.host}:{ws_config.port}")
```

---

### HttpRestChannel

**Import**: `from soothe_daemon.channels.http_rest import HttpRestChannel`

HTTP REST transport for RESTful API access (see [REST API Reference](rest-api.md)).

#### Constructor

```python
HttpRestChannel(
    config: HttpRestConfig,
    manager: ChannelManager,
    *,
    runner: SootheRunner | None = None,
    soothe_config: SootheConfig | None = None,
    session_manager: ClientSessionManager | None = None,
    unified_app: FastAPI | None = None,
    autopilot_service: AutopilotService | None = None,
)
```

**Configuration**:
```yaml
transport:
  http_rest:
    enabled: true
    host: localhost
    port: 8080
    tls_enabled: false
    tls_cert: null
    tls_key: null
    cors_origins: ["*"]
```

**Example**:
```python
from soothe_daemon.channels.http_rest import HttpRestChannel
from soothe_daemon.config.models import HttpRestConfig

http_config = HttpRestConfig(
    host="localhost",
    port=8080,
    cors_origins=["http://localhost:3000"],
)

http_channel = HttpRestChannel(
    http_config,
    manager,
    runner=my_runner,
    soothe_config=config,
    autopilot_service=autopilot_svc,
)

await http_channel.start()
print(f"HTTP REST listening on http://{http_config.host}:{http_config.port}")
```

---

### Platform Channels

Soothe supports integration with external messaging platforms:

#### TelegramChannel

**Import**: `from soothe_daemon.channels.telegram import TelegramChannel`

Telegram bot integration for inbound/outbound messages.

**Configuration**:
```yaml
channels:
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    allowed_chat_ids: [123456789]
```

---

#### SlackChannel

**Import**: `from soothe_daemon.channels.slack import SlackChannel`

Slack bot integration for team collaboration.

**Configuration**:
```yaml
channels:
  slack:
    enabled: true
    bot_token: "${SLACK_BOT_TOKEN}"
    app_token: "${SLACK_APP_TOKEN}"
    signing_secret: "${SLACK_SIGNING_SECRET}"
```

---

#### DiscordChannel

**Import**: `from soothe_daemon.channels.discord import DiscordChannel`

Discord bot integration for community servers.

**Configuration**:
```yaml
channels:
  discord:
    enabled: true
    bot_token: "${DISCORD_BOT_TOKEN}"
    guild_id: 123456789
```

---

## Health Checks

### health_check()

**Import**: `from soothe_daemon.health import health_check`

Comprehensive daemon health check.

#### Signature

```python
async def health_check(
    *,
    include_external: bool = False,
    verbose: bool = False,
) -> HealthReport
```

**Parameters**:
- `include_external`: Check external service connectivity
- `verbose`: Include detailed component information

**Returns**: HealthReport with component statuses

**Example**:
```python
from soothe_daemon.health import health_check

# Basic health check
report = await health_check()

print(f"Overall status: {report.status}")

for component, status in report.components.items():
    print(f"  {component}: {status}")

# Detailed check with external services
report = await health_check(include_external=True, verbose=True)

for component, details in report.details.items():
    print(f"{component}:")
    print(f"  Status: {details['status']}")
    print(f"  Message: {details['message']}")
    if "metrics" in details:
        print(f"  Metrics: {details['metrics']}")
```

---

### HealthReport

**Import**: `from soothe_daemon.health import HealthReport`

Health check report data structure.

```python
class HealthReport(BaseModel):
    """Daemon health report."""
    
    status: str
    """Overall status: 'healthy', 'degraded', 'unhealthy'."""
    
    components: dict[str, str]
    """Component name -> status mapping."""
    
    details: dict[str, dict[str, Any]] = Field(default_factory=dict)
    """Detailed component information."""
    
    timestamp: float
    """Report timestamp."""
    
    uptime_seconds: float
    """Daemon uptime."""
```

---

### Component Health Checks

#### Protocol Health

**Import**: `from soothe_daemon.health.checks.protocol_health import check_protocols`

Check protocol backend health.

```python
async def check_protocols(config: SootheConfig) -> dict[str, Any]:
    """Check all configured protocol backends."""
    ...
```

---

#### Persistence Health

**Import**: `from soothe_daemon.health.checks.persistence_health import check_persistence`

Check database connectivity.

```python
async def check_persistence(config: SootheConfig) -> dict[str, Any]:
    """Check persistence backend connectivity."""
    ...
```

---

#### External API Health

**Import**: `from soothe_daemon.health.checks.external_apis_check import check_external_apis`

Check external service connectivity (OpenAI, Anthropic, etc.).

```python
async def check_external_apis(config: SootheConfig) -> dict[str, Any]:
    """Check external API connectivity."""
    ...
```

---

## RPC Commands

### Command Handlers

RPC commands are handled via WebSocket using structured request/response format.

#### Request Format

```python
{
    "type": "command_request",
    "command": "memory",
    "params": {"action": "clear"},
    "loop_id": "loop-123",
    "request_id": "req-abc"
}
```

#### Response Format

```python
{
    "type": "command_response",
    "command": "memory",
    "data": {"cleared": 5},
    "request_id": "req-abc",
    "loop_id": "loop-123"
}
```

---

### Available Commands

#### `/memory` - Memory Management

```python
{
    "command": "memory",
    "params": {
        "action": "clear" | "recall" | "remember",
        "query": "optional query for recall",
        "content": "optional content for remember"
    }
}
```

---

#### `/policy` - Policy Management

```python
{
    "command": "policy",
    "params": {
        "action": "check" | "list",
        "request": "optional action request"
    }
}
```

---

#### `/thread` - Thread Management

```python
{
    "command": "thread",
    "params": {
        "action": "create" | "suspend" | "resume" | "archive" | "list",
        "thread_id": "optional thread ID"
    }
}
```

---

#### `/history` - Conversation History

```python
{
    "command": "history",
    "params": {
        "limit": 10,
        "include_metadata": true
    }
}
```

---

#### `/clear` - Clear Context

```python
{
    "command": "clear",
    "params": {}
}
```

---

#### `/cancel` - Cancel Execution

```python
{
    "command": "cancel",
    "params": {}
}
```

---

#### `/exit` - Exit Daemon

```python
{
    "command": "exit",
    "params": {}
}
```

---

## ClientSessionManager

**Import**: `from soothe_daemon.server.session import ClientSessionManager`

Manages client sessions and event queues.

#### Constructor

```python
ClientSessionManager(
    *,
    max_queue_size: int = 10000,
)
```

**Parameters**:
- `max_queue_size`: Maximum events per client queue

**Methods**:

##### `create_session()`

```python
async def create_session(
    client_id: str,
    *,
    loop_id: str | None = None,
) -> ClientSession
```

Create a new client session.

**Returns**: ClientSession instance

---

##### `get_session()`

```python
def get_session(client_id: str) -> ClientSession | None
```

Get existing session by client ID.

---

##### `remove_session()`

```python
async def remove_session(client_id: str) -> None
```

Remove and cleanup session.

---

## ClientSession

**Import**: `from soothe_daemon.server.session import ClientSession`

Client session with event queue and metadata.

```python
class ClientSession:
    """Client session with event queue."""
    
    client_id: str
    """Client identifier."""
    
    loop_id: str | None
    """Current loop subscription."""
    
    thread_id: str | None
    """Current thread ID."""
    
    workspace: str | None
    """Current workspace."""
    
    event_queue: asyncio.Queue
    """Event queue for streaming."""
    
    created_at: float
    """Session creation timestamp."""
    
    last_activity: float
    """Last activity timestamp."""
```

---

## Daemon Configuration Models

### WebSocketConfig

**Import**: `from soothe_daemon.config.models import WebSocketConfig`

WebSocket transport configuration.

```python
class WebSocketConfig(BaseModel):
    """WebSocket configuration."""
    
    enabled: bool = True
    """Enable WebSocket transport."""
    
    host: str = "localhost"
    """WebSocket host."""
    
    port: int = 8765
    """WebSocket port."""
    
    max_frame_size: int = 10 * 1024 * 1024  # 10 MiB
    """Maximum frame size."""
    
    ping_interval: int = 30
    """Ping interval for keepalive."""
    
    ping_timeout: int = 60
    """Ping timeout."""
```

---

### HttpRestConfig

**Import**: `from soothe_daemon.config.models import HttpRestConfig`

HTTP REST transport configuration.

```python
class HttpRestConfig(BaseModel):
    """HTTP REST configuration."""
    
    enabled: bool = True
    """Enable HTTP REST transport."""
    
    host: str = "localhost"
    """HTTP host."""
    
    port: int = 8080
    """HTTP port."""
    
    tls_enabled: bool = False
    """Enable TLS/SSL."""
    
    tls_cert: str | None = None
    """TLS certificate path."""
    
    tls_key: str | None = None
    """TLS key path."""
    
    cors_origins: list[str] = ["*"]
    """CORS allowed origins."""
```

---

## See Also

- **[REST API Reference](rest-api.md)** - HTTP REST endpoints documentation
- **[SDK API: WebSocketClient](sdk-api.md#websocket-client)** - WebSocket client usage
- **[Daemon Management Guide](../daemon-management.md)** - Daemon lifecycle management
- **[Multi-Transport Communication](../multi-transport.md)** - Transport architecture
- **[RFC-302 Daemon Communication](../../specs/RFC-302-daemon-communication.md)** - Daemon specification