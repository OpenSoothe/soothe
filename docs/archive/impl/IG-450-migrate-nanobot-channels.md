# IG-450: Migrate nanoBot Channels to soothe-daemon

## Summary

Migrate 11 remaining external chat platform channels from `../nanoBot/nanobot/channels/` to `soothe-daemon/channels/`, adapting them from nanoBot's `BaseChannel` + `MessageBus` architecture to soothe's `Channel` + `ChannelManager` architecture (RFC-620).

## Status

**Phase 1-2 Completed**: Foundation + 3 high-priority channels migrated.

### Completed Channels

| Channel | File | Status | Notes |
|---------|------|--------|-------|
| telegram | telegram.py | ✅ Done | Full RFC-620 Channel, streaming, polling/webhook modes |
| discord | discord.py | ✅ Done | RFC-620 Channel, streaming, app commands, optional import |
| slack | slack.py | ✅ Done | RFC-620 Channel, Socket Mode, thread context, mrkdwn conversion |

### Remaining Channels (Phase 3-6) - 11 channels

| Channel | File | Dependencies | Complexity | Priority |
|---------|------|--------------|------------|----------|
| email | email.py | imaplib, smtplib (stdlib) | Medium (polling) | 4 |
| matrix | matrix.py | matrix-nio (optional) | High (E2E) | 5 |
| signal | signal.py | signal-cli (external) | High (CLI bridge) | 6 |
| whatsapp | whatsapp.py | Node.js bridge | Medium | 7 |
| feishu | feishu.py | lark-oapi | Very High (complex) | 8 |
| dingtalk | dingtalk.py | dingtalk-stream | Medium | 9 |
| qq | qq.py | qq-botpy | Medium | 10 |
| weixin | weixin.py | pycryptodome, qrcode (optional) | High (WeChat) | 11 |
| wecom | wecom.py | wecom-aibot-sdk (optional) | High (WeCom) | 12 |
| msteams | msteams.py | PyJWT, cryptography (optional) | High (Bot Framework) | 13 |
| mochat | mochat.py | python-socketio | Medium | 14 |

## Migration Pattern

Based on completed migrations (telegram, discord, slack), each channel requires:

### 1. Import Changes

```python
# nanoBot imports
from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage, InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base
from nanobot.utils.helpers import safe_filename, split_message

# soothe imports
from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.platform_helpers import safe_filename, split_message
# Remove MessageBus import (use manager)
# Config: simple dataclass-like class (no Pydantic Base inheritance)
```

### 2. Class Definition Changes

```python
# nanoBot pattern
class XxxChannel(BaseChannel):
    name = "xxx"
    display_name = "Xxx"
    
    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self.config: XxxConfig = config

# soothe pattern
class XxxChannel(Channel):
    name = "xxx"
    display_name = "Xxx"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False  # Override if channel supports streaming
    
    def __init__(self, config: Any, manager: ChannelManager):
        super().__init__(config, manager)
        if isinstance(config, dict):
            self.config = XxxConfig(**config)
        else:
            self.config = config
```

### 3. Config Class Changes

```python
# nanoBot pattern (Pydantic Base)
class XxxConfig(Base):
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)

# soothe pattern (simple class)
class XxxConfig:
    enabled: bool = False
    token: str = ""
    allow_from: list[str] = []
    
    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
```

### 4. Send Method Changes

```python
# nanoBot pattern
async def send(self, msg: OutboundMessage) -> None:
    chat_id = msg.chat_id
    content = msg.content
    media = msg.media
    metadata = msg.metadata

# soothe pattern
async def send(self, chat_id: str, message: ChannelMessage) -> None:
    content = message.content
    media = message.media
    metadata = message.metadata
```

### 5. _handle_message Changes

```python
# nanoBot pattern (publishes to bus)
await self.bus.publish_inbound(InboundMessage(
    channel=self.name,
    sender_id=sender_id,
    chat_id=chat_id,
    content=content,
    media=media,
    metadata=metadata,
))

# soothe pattern (returns loop_id)
loop_id = await self._manager.handle_inbound(
    channel=self.name,
    chat_id=chat_id,
    sender_id=sender_id,
    content=content,
    media=media,
    metadata=metadata,
)
return loop_id
```

### 6. Streaming Methods (if supported)

```python
# Both patterns similar, but soothe has explicit supports_streaming flag
async def send_delta(self, chat_id: str, delta: str, metadata: dict | None) -> None:
    # Same implementation pattern
    pass

async def send_reasoning_delta(self, chat_id: str, delta: str, metadata: dict | None) -> None:
    # Same implementation pattern
    pass

async def send_reasoning_end(self, chat_id: str, metadata: dict | None) -> None:
    # Same implementation pattern
    pass
```

### 7. Helper Function Changes

Replace `nanobot.utils.helpers` imports with `soothe_daemon.channels.platform_helpers`:
- `safe_filename()` → same
- `split_message()` → same
- `truncate_text()` → same
- `detect_image_mime()` → same

### 8. Path/Config Changes

Replace `nanobot.config.paths` with direct implementations or manager access:
- `get_media_dir(channel)` → Use `manager._media_dir` or implement locally
- `get_runtime_subdir(name)` → Use `Path.home() / ".soothe" / name`
- `get_data_dir()` → Use `Path.home() / ".soothe"`

## Implementation Steps

### Phase 3: Medium Channels (Day 1)

#### 3.1 Email Channel
- Migrate `email.py` with IMAP polling + SMTP send
- Config: `EmailConfig` with IMAP/SMTP settings
- No streaming support
- Add anti-spoofing DKIM/SPF verification
- Dependencies: stdlib only (imaplib, smtplib)

#### 3.2 WhatsApp Channel  
- Migrate `whatsapp.py` with Node.js bridge WebSocket
- Config: `WhatsAppConfig` with bridge_url, bridge_token
- Optional login method (QR code via npm start)
- No streaming support
- Dependencies: websockets (already in soothe-daemon)

#### 3.3 DingTalk Channel
- Migrate `dingtalk.py` with dingtalk-stream SDK
- Config: `DingTalkConfig` with client_id, client_secret
- No streaming support
- Dependencies: dingtalk-stream (already in pyproject.toml)

#### 3.4 QQ Channel
- Migrate `qq.py` with qq-botpy SDK
- Config: `QQConfig` with app_id, secret
- No streaming support
- Dependencies: qq-botpy (already in pyproject.toml)

### Phase 4: Complex Channels (Day 2)

#### 4.1 Feishu/Lark Channel (~76KB file, most complex)
- Migrate `feishu.py` - largest channel file
- Config: `FeishuConfig` with app_id, app_secret, domain selection
- Streaming support via CardKit streaming API
- Complex markdown rendering, media handling, mentions
- Dependencies: lark-oapi (already in pyproject.toml)

#### 4.2 Matrix Channel
- Migrate `matrix.py` with matrix-nio SDK
- Config: `MatrixConfig` with homeserver, user_id, password/access_token
- Optional E2E encryption support
- Streaming via message editing
- Dependencies: matrix-nio (optional dep group)

#### 4.3 Signal Channel
- Migrate `signal.py` with signal-cli HTTP JSON-RPC
- Config: `SignalConfig` with phone_number, daemon_host/port
- Complex markdown-to-textStyle conversion
- Group message context buffering
- Dependencies: httpx (already in soothe-daemon)

### Phase 5: Chinese Platform Channels (Day 3)

#### 5.1 WeChat (Personal) Channel
- Migrate `weixin.py` with HTTP long-poll API
- Config: `WeixinConfig` with token, base_url, cdn_base_url
- Complex AES encryption/decryption for media
- Typing indicator keepalive loop
- Dependencies: pycryptodome, qrcode (optional dep group)

#### 5.2 WeCom (Enterprise WeChat) Channel
- Migrate `wecom.py` with wecom-aibot-sdk WebSocket
- Config: `WecomConfig` with bot_id, secret
- WebSocket upload protocol for media
- Dependencies: wecom-aibot-sdk-python (optional dep group)

#### 5.3 Microsoft Teams Channel
- Migrate `msteams.py` with Bot Framework HTTP webhook
- Config: `MSTeamsConfig` with app_id, app_password, tenant_id
- Conversation reference persistence
- JWT token validation for inbound auth
- Dependencies: PyJWT, cryptography (optional dep group)

### Phase 6: Finalization (Day 4)

#### 6.1 Mochat Channel
- Migrate `mochat.py` with Socket.IO + HTTP polling fallback
- Config: `MochatConfig` with claw_token, sessions, panels
- Complex delay/mention handling for groups
- Cursor persistence for session state

#### 6.2 Update __init__.py
- Export all migrated channels
- Update `__all__` list with conditional imports for optional deps

#### 6.3 Integration Testing
- Run full verification: `./scripts/verify_finally.sh`
- Test channel discovery
- Test config schema validation

#### 6.4 Documentation Updates
- Update RFC-620 with channel list
- Add channel configuration examples to user guide

## Per-Channel Migration Checklist

For each channel:

1. Copy channel file to `soothe_daemon/channels/`
2. Update imports (see Migration Pattern §1)
3. Update class definition (see §2)
4. Update config class (see §3)
5. Update `send()` signature (see §4)
6. Update `_handle_message()` to use manager (see §5)
7. Update streaming methods if supported (see §6)
8. Replace helper imports with platform_helpers (see §7)
9. Replace path/config imports (see §8)
10. Add optional import guard if channel has optional deps:
    ```python
    try:
        from soothe_daemon.channels.xxx import XxxChannel
    except ImportError:
        XxxChannel = None  # type: ignore
    ```
11. Update tests (if any):
    - Mock `ChannelManager` instead of `MessageBus`
    - Use `ChannelMessage` instead of `OutboundMessage`
    - Place tests in `packages/soothe-daemon/tests/unit/channels/`

## Dependencies Status

Already configured in pyproject.toml:

### Core Dependencies (installed by default)
- python-telegram-bot[socks,webhooks] >=22.6
- slack-sdk >=3.39.0
- slackify-markdown >=0.2.0
- lark-oapi >=1.5.0
- dingtalk-stream >=0.24.0
- qq-botpy >=1.2.0
- httpx >=0.28.0

### Optional Dependency Groups
- `[discord]`: discord.py >=2.5.2
- `[matrix]`: matrix-nio + mistune + nh3
- `[wecom]`: wecom-aibot-sdk-python
- `[weixin]`: qrcode[pil] + pycryptodome
- `[msteams]`: PyJWT + cryptography
- `[all-channels]`: All optional groups

## Risk Assessment

### High-Risk Items

1. **Feishu channel** (~76KB) - Very complex, extensive test coverage
   - Mitigation: Migrate in single careful pass, preserve all helper functions

2. **WeChat iLink protocol** - Complex AES encryption/decryption
   - Mitigation: Copy crypto helpers unchanged, only adapt interfaces

3. **Signal textStyle conversion** - UTF-16 offset math
   - Mitigation: Copy helper functions unchanged, verify encoding

### Medium-Risk Items

1. **Optional dependency imports** - Graceful degradation
   - Mitigation: Use try/except ImportError guards

2. **Config validation** - Both use Pydantic-compatible patterns
   - Mitigation: Test config parsing for each channel

## Success Criteria

1. All 11 remaining channels migrated and working
2. All tests passing (`./scripts/verify_finally.sh`)
3. Zero linting errors
4. Graceful degradation when optional deps missing
5. Channel discovery works for all built-in channels
6. Streaming works where supported (Telegram, Discord, Slack, Feishu, Matrix)

## References

- RFC-620: Channel Architecture Specification
- IG-449: Channel Plugin Architecture (completed)
- nanoBot channels: `../nanoBot/nanobot/channels/`
- Migrated channels: `packages/soothe-daemon/src/soothe_daemon/channels/`