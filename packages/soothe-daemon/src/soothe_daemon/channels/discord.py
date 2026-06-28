"""Discord channel implementation using discord.py.

Migrated from nanoBot with adaptations for soothe-daemon Channel architecture (RFC-620).
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.platform_helpers import safe_filename, split_message

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if TYPE_CHECKING:
    import aiohttp
    import discord
    from discord import app_commands
    from discord.abc import Messageable

# Runtime imports — the TYPE_CHECKING block above is erased at runtime, so these
# real imports are required for runtime resolution (discord.Client,
# app_commands.CommandTree, and Messageable are used in class bodies below).
if DISCORD_AVAILABLE:
    import discord
    from discord import app_commands
    from discord.abc import Messageable

logger = logging.getLogger(__name__)

# Discord limits
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB
MAX_MESSAGE_LEN = 2000
TYPING_INTERVAL_S = 8
_STREAM_EDIT_INTERVAL = 0.8


@dataclass
class _StreamBuf:
    """Per-chat streaming accumulator for progressive message edits."""

    text: str = ""
    message: Any | None = None
    last_edit: float = 0.0
    stream_id: str | None = None


class DiscordConfig:
    """Discord channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = []
    allow_channels: list[str] = []  # Allowed channel IDs (empty = all)
    intents: int = 37377
    group_policy: Literal["mention", "open"] = "mention"
    read_receipt_emoji: str = "👀"
    working_emoji: str = "🔧"
    working_emoji_delay: float = 2.0
    streaming: bool = True
    proxy: str | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


if DISCORD_AVAILABLE:

    class DiscordBotClient(discord.Client):
        """discord.py client that forwards events to the channel."""

        def __init__(
            self,
            channel: DiscordChannel,
            *,
            intents: discord.Intents,
            proxy: str | None = None,
            proxy_auth: aiohttp.BasicAuth | None = None,
        ) -> None:
            super().__init__(intents=intents, proxy=proxy, proxy_auth=proxy_auth)
            self._channel = channel
            self.tree = app_commands.CommandTree(self)
            self._register_app_commands()

        async def on_ready(self) -> None:
            self._channel._bot_user_id = str(self.user.id) if self.user else None
            logger.info("[Discord] Bot connected as user %s", self._channel._bot_user_id)
            try:
                synced = await self.tree.sync()
                logger.info("[Discord] App commands synced: %d", len(synced))
            except Exception as e:
                logger.warning("[Discord] App command sync failed: %s", e)

        async def on_message(self, message: discord.Message) -> None:
            await self._channel._handle_discord_message(message)

        async def on_thread_delete(self, thread: discord.Thread) -> None:
            self._channel._forget_channel(thread)

        async def on_thread_update(self, before: discord.Thread, after: discord.Thread) -> None:
            if getattr(after, "archived", False):
                self._channel._forget_channel(after)
            else:
                self._channel._remember_channel(after)

        async def _reply_ephemeral(self, interaction: discord.Interaction, text: str) -> bool:
            """Send an ephemeral interaction response."""
            try:
                await interaction.response.send_message(text, ephemeral=True)
                return True
            except Exception as e:
                logger.warning("[Discord] Interaction response failed: %s", e)
                return False

        async def _resolve_interaction_channel(
            self, interaction: discord.Interaction
        ) -> Any | None:
            channel_id = interaction.channel_id
            if channel_id is None:
                return None
            channel = getattr(interaction, "channel", None) or self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning(
                        "[Discord] Interaction channel %s unavailable: %s", channel_id, e
                    )
                    return None
            self._channel._remember_channel(channel)
            return channel

        async def _interaction_channel_allowed(
            self, interaction: discord.Interaction, channel: Any | None
        ) -> bool:
            allow_channels = self._channel.config.allow_channels
            if not allow_channels:
                return True
            if channel is None:
                channel_id = interaction.channel_id
                return channel_id is not None and str(channel_id) in allow_channels
            channel_ids = self._channel._channel_allow_keys(channel)
            return not channel_ids.isdisjoint(allow_channels)

        async def _forward_slash_command(
            self, interaction: discord.Interaction, command_text: str
        ) -> None:
            sender_id = str(interaction.user.id)
            channel_id = interaction.channel_id

            if channel_id is None:
                logger.warning("[Discord] Slash command missing channel_id: %s", command_text)
                return

            if not self._channel.is_allowed(sender_id):
                await self._reply_ephemeral(interaction, "You are not allowed to use this bot.")
                return

            channel = await self._resolve_interaction_channel(interaction)
            if not await self._interaction_channel_allowed(interaction, channel):
                await self._reply_ephemeral(
                    interaction, "This channel is not allowed for this bot."
                )
                return

            await self._reply_ephemeral(interaction, f"Processing {command_text}...")

            metadata: dict[str, Any] = {
                "interaction_id": str(interaction.id),
                "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                "is_slash_command": True,
            }
            if channel is not None:
                parent_channel_id = self._channel._channel_parent_key(channel)
                if parent_channel_id is not None:
                    metadata["parent_channel_id"] = parent_channel_id
                    metadata["context_chat_id"] = parent_channel_id
                    metadata["thread_id"] = str(channel_id)

            await self._channel._handle_message(
                sender_id=sender_id,
                chat_id=str(channel_id),
                content=command_text,
                metadata=metadata,
            )

        def _register_app_commands(self) -> None:
            commands = (
                ("new", "Start a new conversation", "/new"),
                ("stop", "Stop the current task", "/stop"),
                ("status", "Show bot status", "/status"),
                ("help", "Show available commands", "/help"),
            )

            for name, description, command_text in commands:

                @self.tree.command(name=name, description=description)
                async def command_handler(
                    interaction: discord.Interaction, _command_text: str = command_text
                ) -> None:
                    await self._forward_slash_command(interaction, _command_text)

            @self.tree.command(name="model", description="Show or switch runtime model preset")
            @app_commands.describe(preset="Optional model preset name")
            async def model_command(
                interaction: discord.Interaction, preset: str | None = None
            ) -> None:
                preset = (preset or "").strip()
                command_text = f"/model {preset}" if preset else "/model"
                await self._forward_slash_command(interaction, command_text)

            @self.tree.error
            async def on_app_command_error(
                interaction: discord.Interaction, error: app_commands.AppCommandError
            ) -> None:
                command_name = interaction.command.qualified_name if interaction.command else "?"
                logger.warning(
                    "[Discord] App command failed user=%s channel=%s cmd=%s error=%s",
                    interaction.user.id,
                    interaction.channel_id,
                    command_name,
                    error,
                )

        async def send_outbound(self, chat_id: str, message: ChannelMessage) -> None:
            """Send a ChannelMessage using Discord transport."""
            channel_id = int(chat_id)

            channel = self._channel._known_channels.get(chat_id) or self.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning("[Discord] Channel %s unavailable: %s", chat_id, e)
                    return

            reference, mention_settings = self._build_reply_context(channel, message.reply_to)
            sent_media = False
            failed_media: list[str] = []

            for index, media_path in enumerate(message.media or []):
                if await self._send_file(
                    channel,
                    media_path,
                    reference=reference if index == 0 else None,
                    mention_settings=mention_settings,
                ):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            for index, chunk in enumerate(
                self._build_chunks(message.content or "", failed_media, sent_media)
            ):
                kwargs: dict[str, Any] = {"content": chunk}
                if index == 0 and reference is not None and not sent_media:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                await channel.send(**kwargs)

        async def _send_file(
            self,
            channel: Messageable,
            file_path: str,
            *,
            reference: discord.PartialMessage | None,
            mention_settings: discord.AllowedMentions,
        ) -> bool:
            """Send a file attachment."""
            path = Path(file_path)
            if not path.is_file():
                logger.warning("[Discord] File not found: %s", file_path)
                return False

            if path.stat().st_size > MAX_ATTACHMENT_BYTES:
                logger.warning("[Discord] File too large (>20MB): %s", path.name)
                return False

            try:
                kwargs: dict[str, Any] = {"file": discord.File(path)}
                if reference is not None:
                    kwargs["reference"] = reference
                    kwargs["allowed_mentions"] = mention_settings
                await channel.send(**kwargs)
                logger.info("[Discord] File sent: %s", path.name)
                return True
            except Exception:
                logger.exception("[Discord] Error sending file %s", path.name)
                return False

        @staticmethod
        def _build_chunks(content: str, failed_media: list[str], sent_media: bool) -> list[str]:
            """Build outbound text chunks."""
            chunks = split_message(content, MAX_MESSAGE_LEN)
            if chunks or not failed_media or sent_media:
                return chunks
            fallback = "\n".join(f"[attachment: {name} - send failed]" for name in failed_media)
            return split_message(fallback, MAX_MESSAGE_LEN)

        def _build_reply_context(
            self, channel: Messageable, reply_to: str | None
        ) -> tuple[discord.PartialMessage | None, discord.AllowedMentions]:
            """Build reply context for outbound messages."""
            mention_settings = discord.AllowedMentions(replied_user=False)
            if not reply_to:
                return None, mention_settings
            try:
                message_id = int(reply_to)
            except ValueError:
                logger.warning("[Discord] Invalid reply target: %s", reply_to)
                return None, mention_settings

            return channel.get_partial_message(message_id), mention_settings


class DiscordChannel(Channel):
    """Discord channel using discord.py.

    Implements RFC-620 Channel interface with streaming support.
    """

    name = "discord"
    display_name = "Discord"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "token": "",
            "allow_from": [],
            "allow_channels": [],
            "streaming": True,
        }

    @staticmethod
    def _channel_key(channel_or_id: Any) -> str:
        """Normalize channel objects and ids to string key."""
        channel_id = getattr(channel_or_id, "id", channel_or_id)
        return str(channel_id)

    @classmethod
    def _channel_allow_keys(cls, channel: Any) -> set[str]:
        """Return channel IDs that satisfy allow_channels."""
        keys = {cls._channel_key(channel)}
        if parent_key := cls._channel_parent_key(channel):
            keys.add(parent_key)
        return keys

    @classmethod
    def _channel_parent_key(cls, channel: Any) -> str | None:
        """Return parent channel key for threads."""
        parent_id = getattr(channel, "parent_id", None)
        if parent_id is not None:
            return cls._channel_key(parent_id)
        parent = getattr(channel, "parent", None)
        if parent is not None:
            return cls._channel_key(parent)
        return None

    def __init__(self, config: Any, manager: Any) -> None:
        """Initialize Discord channel.

        Args:
            config: Discord configuration.
            manager: ChannelManager for inbound routing.
        """
        super().__init__(config, manager)
        if isinstance(config, dict):
            self.config = DiscordConfig(**config)
        else:
            self.config = config
        self._client: DiscordBotClient | None = None
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._bot_user_id: str | None = None
        self._pending_reactions: dict[str, Any] = {}
        self._working_emoji_tasks: dict[str, asyncio.Task[None]] = {}
        self._stream_bufs: dict[str, _StreamBuf] = {}
        self._known_channels: dict[str, Any] = {}

    def _remember_channel(self, channel: Any) -> None:
        self._known_channels[self._channel_key(channel)] = channel

    def _forget_channel(self, channel_or_id: Any) -> None:
        self._known_channels.pop(self._channel_key(channel_or_id), None)

    async def start(self) -> None:
        """Start the Discord client."""
        if not DISCORD_AVAILABLE:
            logger.error("[Discord] discord.py not installed. Run: pip install soothe-daemon")
            return

        if not self.config.token:
            logger.error("[Discord] Bot token not configured")
            return

        try:
            intents = discord.Intents.none()
            intents.value = self.config.intents

            proxy_auth = None
            has_user = bool(self.config.proxy_username)
            has_pass = bool(self.config.proxy_password)
            if has_user and has_pass:
                import aiohttp

                proxy_auth = aiohttp.BasicAuth(
                    login=self.config.proxy_username,
                    password=self.config.proxy_password,
                )
            elif has_user != has_pass:
                logger.warning(
                    "[Discord] Proxy auth incomplete: both username and password required"
                )

            self._client = DiscordBotClient(
                self,
                intents=intents,
                proxy=self.config.proxy,
                proxy_auth=proxy_auth,
            )
        except Exception:
            logger.exception("[Discord] Failed to initialize client")
            self._client = None
            self._running = False
            return

        self._running = True
        logger.info("[Discord] Starting client...")

        try:
            await self._client.start(self.config.token)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[Discord] Client startup failed")
        finally:
            self._running = False
            await self._reset_runtime_state(close_client=True)

    async def stop(self) -> None:
        """Stop the Discord channel."""
        self._running = False
        await self._reset_runtime_state(close_client=True)

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send a message through Discord.

        Args:
            chat_id: Discord channel ID.
            message: ChannelMessage to send.
        """
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("[Discord] Client not ready; dropping outbound message")
            return

        is_progress = message.is_progress()

        try:
            await client.send_outbound(chat_id, message)
        except Exception:
            logger.exception("[Discord] Error sending message")
            raise
        finally:
            if not is_progress:
                await self._stop_typing(chat_id)
                await self._clear_reactions(chat_id)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Stream incremental text via progressive message editing."""
        client = self._client
        if client is None or not client.is_ready():
            logger.warning("[Discord] Client not ready; dropping stream delta")
            return

        meta = metadata or {}
        stream_id = meta.get("_stream_id")

        if meta.get("_stream_end"):
            buf = self._stream_bufs.get(chat_id)
            if not buf or buf.message is None or not buf.text:
                return
            if stream_id and buf.stream_id and buf.stream_id != stream_id:
                return
            await self._finalize_stream(chat_id, buf)
            return

        buf = self._stream_bufs.get(chat_id)
        if buf is None or (stream_id and buf.stream_id and buf.stream_id != stream_id):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id

        buf.text += delta
        if not buf.text.strip():
            return

        target = await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("[Discord] Stream target %s unavailable", chat_id)
            return

        now = time.monotonic()
        if buf.message is None:
            buf.message = await target.send(content=buf.text)
            buf.last_edit = now
            return

        if (now - buf.last_edit) < _STREAM_EDIT_INTERVAL:
            return

        await buf.message.edit(content=DiscordBotClient._build_chunks(buf.text, [], False)[0])
        buf.last_edit = now

    async def _handle_discord_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages."""
        if self._bot_user_id and str(message.author.id) == self._bot_user_id:
            return
        if self._is_system_message(message):
            return

        sender_id = str(message.author.id)
        channel_id = self._channel_key(message.channel)
        self._remember_channel(message.channel)
        content = message.content or ""

        if not self._should_accept_inbound(message, sender_id, content):
            return

        media_paths, attachment_markers = await self._download_attachments(message.attachments)
        full_content = self._compose_inbound_content(content, attachment_markers)
        metadata = self._build_inbound_metadata(message)

        await self._start_typing(message.channel)

        try:
            await message.add_reaction(self.config.read_receipt_emoji)
            self._pending_reactions[channel_id] = message
        except Exception as e:
            logger.debug("[Discord] Failed to add read receipt: %s", e)

        async def _delayed_working_emoji() -> None:
            await asyncio.sleep(self.config.working_emoji_delay)
            with suppress(Exception):
                await message.add_reaction(self.config.working_emoji)

        self._working_emoji_tasks[channel_id] = asyncio.create_task(_delayed_working_emoji())

        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content=full_content,
            media=media_paths,
            metadata=metadata,
        )

    async def _resolve_channel(self, chat_id: str) -> Any | None:
        """Resolve Discord channel from cache or network."""
        client = self._client
        if client is None or not client.is_ready():
            return None
        channel = self._known_channels.get(chat_id)
        if channel is not None:
            return channel
        channel_id = int(chat_id)
        channel = client.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await client.fetch_channel(channel_id)
        except Exception as e:
            logger.warning("[Discord] Channel %s unavailable: %s", chat_id, e)
            return None

    async def _finalize_stream(self, chat_id: str, buf: _StreamBuf) -> None:
        """Finalize streaming message."""
        chunks = DiscordBotClient._build_chunks(buf.text, [], False)
        if not chunks:
            self._stream_bufs.pop(chat_id, None)
            return

        await buf.message.edit(content=chunks[0])

        target = getattr(buf.message, "channel", None) or await self._resolve_channel(chat_id)
        if target is None:
            logger.warning("[Discord] Stream follow-up target %s unavailable", chat_id)
            self._stream_bufs.pop(chat_id, None)
            return

        for extra_chunk in chunks[1:]:
            await target.send(content=extra_chunk)

        self._stream_bufs.pop(chat_id, None)
        await self._stop_typing(chat_id)
        await self._clear_reactions(chat_id)

    def _should_accept_inbound(
        self, message: discord.Message, sender_id: str, content: str
    ) -> bool:
        """Check if inbound message should be processed."""
        if not self.is_allowed(sender_id):
            return False
        allow_channels = self.config.allow_channels
        if allow_channels:
            channel_ids = self._channel_allow_keys(message.channel)
            if channel_ids.isdisjoint(allow_channels):
                return False
        if message.guild and not self._should_respond_in_group(message, content):
            return False
        return True

    async def _download_attachments(
        self, attachments: list[discord.Attachment]
    ) -> tuple[list[str], list[str]]:
        """Download attachments and return paths + markers."""
        import tempfile

        media_paths: list[str] = []
        markers: list[str] = []

        for attachment in attachments:
            filename = attachment.filename or "attachment"
            if attachment.size and attachment.size > MAX_ATTACHMENT_BYTES:
                markers.append(f"[attachment: {filename} - too large]")
                continue
            try:
                safe_name = safe_filename(filename)
                fd, file_path = tempfile.mkstemp(suffix=f"_{safe_name}", prefix="discord_")
                Path(file_path).write_bytes(await attachment.read())
                media_paths.append(file_path)
                markers.append(f"[attachment: {Path(file_path).name}]")
            except Exception as e:
                logger.warning("[Discord] Failed to download attachment: %s", e)
                markers.append(f"[attachment: {filename} - download failed]")

        return media_paths, markers

    @staticmethod
    def _compose_inbound_content(content: str, attachment_markers: list[str]) -> str:
        """Combine message text with attachment markers."""
        content_parts = [content] if content else []
        content_parts.extend(attachment_markers)
        return "\n".join(part for part in content_parts if part) or "[empty message]"

    @staticmethod
    def _is_system_message(message: discord.Message) -> bool:
        """Return True for Discord system messages."""
        message_type = getattr(message, "type", discord.MessageType.default)
        return message_type not in {discord.MessageType.default, discord.MessageType.reply}

    @staticmethod
    def _build_inbound_metadata(message: discord.Message) -> dict[str, str | None]:
        """Build metadata for inbound messages."""
        reply_to = (
            str(message.reference.message_id)
            if message.reference and message.reference.message_id
            else None
        )
        return {
            "message_id": str(message.id),
            "guild_id": str(message.guild.id) if message.guild else None,
            "reply_to": reply_to,
        }

    def _should_respond_in_group(self, message: discord.Message, content: str) -> bool:
        """Check if bot should respond in guild channel."""
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            bot_user_id = self._bot_user_id
            if bot_user_id is None and self._client and self._client.user:
                bot_user_id = str(self._client.user.id)
            if bot_user_id is None:
                return False

            if any(str(user.id) == bot_user_id for user in message.mentions):
                return True
            if f"<@{bot_user_id}>" in content or f"<@!{bot_user_id}>" in content:
                return True
            if self._references_bot_message(message, bot_user_id):
                return True

            return False

        return True

    @staticmethod
    def _references_bot_message(message: discord.Message, bot_user_id: str) -> bool:
        """Return True when reply targets bot's message."""
        reference = getattr(message, "reference", None)
        if reference is None:
            return False
        referenced_message = getattr(reference, "resolved", None) or getattr(
            reference, "cached_message", None
        )
        author = getattr(referenced_message, "author", None)
        return str(getattr(author, "id", "")) == bot_user_id

    async def _start_typing(self, channel: Messageable) -> None:
        """Start periodic typing indicator."""
        channel_id = self._channel_key(channel)
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            while self._running:
                try:
                    async with channel.typing():
                        await asyncio.sleep(TYPING_INTERVAL_S)
                except asyncio.CancelledError:
                    return
                except Exception:
                    return

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """Stop typing indicator."""
        task = self._typing_tasks.pop(self._channel_key(channel_id), None)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _clear_reactions(self, chat_id: str) -> None:
        """Remove pending reactions."""
        task = self._working_emoji_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

        msg_obj = self._pending_reactions.pop(chat_id, None)
        if msg_obj is None:
            return
        bot_user = self._client.user if self._client else None
        for emoji in (self.config.read_receipt_emoji, self.config.working_emoji):
            with suppress(Exception):
                await msg_obj.remove_reaction(emoji, bot_user)

    async def _reset_runtime_state(self, close_client: bool) -> None:
        """Reset client and typing state."""
        channel_ids = list(self._typing_tasks)
        for channel_id in channel_ids:
            await self._stop_typing(channel_id)
        self._stream_bufs.clear()
        self._known_channels.clear()
        if close_client and self._client and not self._client.is_closed():
            try:
                await self._client.close()
            except Exception as e:
                logger.warning("[Discord] Client close failed: %s", e)
        self._client = None
        self._bot_user_id = None


# Export conditionally
if DISCORD_AVAILABLE:
    __all__ = ["DiscordChannel", "DiscordConfig"]
else:
    __all__ = []
