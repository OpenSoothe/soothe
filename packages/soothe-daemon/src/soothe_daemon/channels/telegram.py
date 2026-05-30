"""Telegram channel implementation using python-telegram-bot.

Migrated from nanoBot with adaptations for soothe-daemon Channel architecture (RFC-620).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    ReplyParameters,
    Update,
)
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.platform_helpers import split_message

logger = logging.getLogger(__name__)

# Telegram message limits
TELEGRAM_MAX_MESSAGE_LEN = 4000  # Split raw markdown at 4000 for safety margin
TELEGRAM_HTML_MAX_LEN = 4096  # Telegram's actual API limit
TELEGRAM_REPLY_CONTEXT_MAX_LEN = 4000

# Retry configuration
_SEND_MAX_RETRIES = 3
_SEND_RETRY_BASE_DELAY = 0.5
_STREAM_EDIT_INTERVAL_DEFAULT = 0.6


def _escape_telegram_html(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tool_hint_to_telegram_blockquote(text: str) -> str:
    """Render tool hints as an expandable blockquote."""
    return f"<blockquote expandable>{_escape_telegram_html(text)}</blockquote>" if text else ""


def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"__(.+?)__", r"\1", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    return s.strip()


def _strip_md_block(text: str) -> str:
    """Strip markdown for plain-text preview during streaming."""
    # Code blocks -> just the code
    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", r"\1", text)
    # Headers -> plain text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)
    # Blockquotes
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)
    # Bold / italic / strikethrough
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Links -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bullet lists
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)
    # Numbered lists
    text = re.sub(r"^(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)
    return text


def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return "\n".join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([""] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return "  ".join(f"{c}{' ' * (w - dw(c))}" for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append("  ".join("─" * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return "\n".join(out)


def _markdown_to_telegram_html(text: str) -> str:
    """Convert markdown to Telegram-safe HTML."""
    if not text:
        return ""

    # Extract and protect code blocks
    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", save_code_block, text)

    # Convert markdown tables
    lines = text.split("\n")
    rebuilt: list[str] = []
    li = 0
    while li < len(lines):
        if re.match(r"^\s*\|.+\|", lines[li]):
            tbl: list[str] = []
            while li < len(lines) and re.match(r"^\s*\|.+\|", lines[li]):
                tbl.append(lines[li])
                li += 1
            box = _render_table_box(tbl)
            if box != "\n".join(tbl):
                code_blocks.append(box)
                rebuilt.append(f"\x00CB{len(code_blocks) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[li])
            li += 1
    text = "\n".join(rebuilt)

    # Extract inline code
    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # Headers -> bold markers
    text = re.sub(r"^#{1,6}\s+(.+)$", r"⟪B⟫\1⟪/B⟫", text, flags=re.MULTILINE)

    # Blockquotes -> plain text
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)

    # Escape HTML
    text = _escape_telegram_html(text)

    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)

    # Strikethrough
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Bullet lists
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # Numbered lists
    text = re.sub(r"^(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        escaped = _escape_telegram_html(code)
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # Restore code blocks
    for i, code in enumerate(code_blocks):
        escaped = _escape_telegram_html(code)
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    # Restore header bold markers
    text = text.replace("⟪B⟫", "<b>").replace("⟪/B⟫", "</b>")

    return text


@dataclass
class _StreamBuf:
    """Per-chat streaming accumulator for progressive message editing."""

    text: str = ""
    message_id: int | None = None
    last_edit: float = 0.0
    stream_id: str | None = None


@dataclass
class _QueuedTelegramUpdate:
    """Telegram update staged for ordered processing."""

    kind: Literal["command", "message"]
    update: Update
    context: Any
    sort_key: tuple[int, int]


class TelegramConfig:
    """Telegram channel configuration (Pydantic-like for soothe)."""

    enabled: bool = False
    token: str = ""
    mode: Literal["polling", "webhook"] = "polling"
    allow_from: list[str] = []
    proxy: str | None = None
    reply_to_message: bool = False
    react_emoji: str = "👀"
    group_policy: Literal["open", "mention"] = "mention"
    connection_pool_size: int = 32
    pool_timeout: float = 5.0
    streaming: bool = True
    inline_keyboards: bool = False
    stream_edit_interval: float = _STREAM_EDIT_INTERVAL_DEFAULT
    webhook_url: str = ""
    webhook_listen_host: str = "127.0.0.1"
    webhook_listen_port: int = 8081
    webhook_path: str = "/telegram"
    webhook_secret_token: str = ""
    webhook_max_connections: int = 4

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


class TelegramChannel(Channel):
    """Telegram channel using polling or webhook mode.

    Implements RFC-620 Channel interface with full streaming support.
    """

    name = "telegram"
    display_name = "Telegram"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    # Bot commands registered with Telegram
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("status", "Show bot status"),
        BotCommand("help", "Show available commands"),
    ]

    # Regex for slash commands
    TELEGRAM_SLASH_COMMAND_RE = re.compile(
        r"^/(?:new|stop|restart|status|help)(?:@\w+)?(?:\s+.*)?$"
    )

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "token": "",
            "mode": "polling",
            "allow_from": [],
            "streaming": True,
        }

    def __init__(self, config: Any, manager: Any) -> None:
        """Initialize Telegram channel.

        Args:
            config: Telegram configuration (dict or TelegramConfig).
            manager: ChannelManager for inbound routing.
        """
        super().__init__(config, manager)
        if isinstance(config, dict):
            self.config = TelegramConfig(**config)
        else:
            self.config = config
        self._app: Application | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self._message_threads: dict[tuple[str, int], int] = {}
        self._bot_user_id: int | None = None
        self._bot_username: str | None = None
        self._stream_bufs: dict[str, _StreamBuf] = {}
        self._inbound_buffers: dict[str, list[_QueuedTelegramUpdate]] = {}
        self._inbound_workers: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the Telegram bot."""
        if not self.config.token:
            logger.error("[Telegram] bot token not configured")
            return

        self._running = True

        proxy = self.config.proxy or None

        # Configure HTTPX request pools
        api_request = HTTPXRequest(
            connection_pool_size=self.config.connection_pool_size,
            pool_timeout=self.config.pool_timeout,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=proxy,
        )
        poll_request = HTTPXRequest(
            connection_pool_size=4,
            pool_timeout=self.config.pool_timeout,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=proxy,
        )
        builder = (
            Application.builder()
            .token(self.config.token)
            .request(api_request)
            .get_updates_request(poll_request)
        )
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)

        # Register handlers
        self._app.add_handler(MessageHandler(filters.Regex(r"^/start(?:@\w+)?$"), self._on_start))
        self._app.add_handler(
            MessageHandler(filters.Regex(self.TELEGRAM_SLASH_COMMAND_RE), self._forward_command)
        )
        self._app.add_handler(MessageHandler(filters.Regex(r"^/help(?:@\w+)?$"), self._on_help))
        self._app.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.VIDEO
                    | filters.VIDEO_NOTE
                    | filters.ANIMATION
                    | filters.VOICE
                    | filters.AUDIO
                    | filters.Document.ALL
                    | filters.LOCATION
                )
                & ~filters.COMMAND,
                self._on_message,
            )
        )

        if self.config.inline_keyboards:
            self._app.add_handler(CallbackQueryHandler(self._on_callback_query))
            allowed_updates = ["message", "callback_query"]
        else:
            allowed_updates = ["message"]

        logger.info("[Telegram] Starting bot (%s mode)...", self.config.mode)

        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        logger.info("[Telegram] @%s connected", bot_info.username)

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
        except Exception as e:
            logger.warning("[Telegram] Failed to register commands: %s", e)

        if self.config.mode == "webhook":
            await self._app.updater.start_webhook(
                listen=self.config.webhook_listen_host,
                port=self.config.webhook_listen_port,
                url_path=self.config.webhook_path.lstrip("/"),
                webhook_url=self.config.webhook_url.strip(),
                allowed_updates=allowed_updates,
                secret_token=self.config.webhook_secret_token.strip(),
                max_connections=self.config.webhook_max_connections,
            )
        else:
            await self._app.updater.start_polling(
                allowed_updates=allowed_updates,
                error_callback=self._on_polling_error,
            )

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False

        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()

        for task in self._inbound_workers.values():
            task.cancel()
        self._inbound_workers.clear()
        self._inbound_buffers.clear()

        if self._app:
            logger.info("[Telegram] Stopping bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send a message through Telegram.

        Args:
            chat_id: Telegram chat ID.
            message: ChannelMessage to send.
        """
        if not self._app:
            logger.warning("[Telegram] bot not running")
            return

        # Stop typing for final responses
        if not message.is_progress():
            self._stop_typing(chat_id)
            if reply_msg_id := message.metadata.get("message_id"):
                with suppress(ValueError):
                    await self._remove_reaction(chat_id, int(reply_msg_id))

        try:
            int_chat_id = int(chat_id)
        except ValueError:
            logger.error("[Telegram] Invalid chat_id: %s", chat_id)
            return

        reply_params = None
        if self.config.reply_to_message:
            reply_msg_id = message.metadata.get("message_id")
            if reply_msg_id:
                reply_params = ReplyParameters(
                    message_id=reply_msg_id, allow_sending_without_reply=True
                )

        thread_kwargs = {}
        msg_thread_id = message.metadata.get("message_thread_id")
        if msg_thread_id:
            thread_kwargs["message_thread_id"] = msg_thread_id

        # Send media files
        for media_path in message.media or []:
            await self._send_media(int_chat_id, media_path, reply_params, thread_kwargs)

        # Send text content
        if message.content and message.content != "[empty message]":
            render_as_blockquote = message.is_tool_hint()
            buttons = message.buttons
            reply_markup = self._build_keyboard(buttons) if buttons else None
            text = message.content
            if buttons and reply_markup is None:
                text = f"{text}\n\n{self._buttons_as_text(buttons)}"
            chunks = split_message(text, TELEGRAM_MAX_MESSAGE_LEN)
            for i, chunk in enumerate(chunks):
                is_last = i == len(chunks) - 1
                await self._send_text(
                    int_chat_id,
                    chunk,
                    reply_params,
                    thread_kwargs,
                    render_as_blockquote=render_as_blockquote,
                    reply_markup=reply_markup if is_last else None,
                )

    async def send_delta(
        self,
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Stream incremental text chunk via progressive message editing."""
        if not self._app:
            return
        meta = metadata or {}
        int_chat_id = int(chat_id)
        stream_id = meta.get("_stream_id")

        # Handle stream end
        if meta.get("_stream_end"):
            buf = self._stream_bufs.get(chat_id)
            if not buf or not buf.message_id or not buf.text:
                return
            if stream_id and buf.stream_id and buf.stream_id != stream_id:
                return
            self._stop_typing(chat_id)
            if reply_msg_id := meta.get("message_id"):
                with suppress(ValueError):
                    await self._remove_reaction(chat_id, int(reply_msg_id))
            await self._finalize_stream(int_chat_id, buf, meta)
            self._stream_bufs.pop(chat_id, None)
            return

        # Handle stream delta
        buf = self._stream_bufs.get(chat_id)
        if buf is None or (stream_id and buf.stream_id and buf.stream_id != stream_id):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id
        buf.text += delta

        if not buf.text.strip():
            return

        await self._edit_stream_message(int_chat_id, buf, meta)

    async def _finalize_stream(self, chat_id: int, buf: _StreamBuf, meta: dict[str, Any]) -> None:
        """Finalize streaming message with HTML formatting."""
        thread_kwargs = {}
        if msg_thread_id := meta.get("message_thread_id"):
            thread_kwargs["message_thread_id"] = msg_thread_id

        raw_text = buf.text
        html = _markdown_to_telegram_html(raw_text)

        if len(html) <= TELEGRAM_HTML_MAX_LEN:
            primary_html = html
            extra_chunks = []
        else:
            html_chunks = split_message(html, TELEGRAM_HTML_MAX_LEN)
            primary_html = html_chunks[0]
            extra_chunks = html_chunks[1:]

        try:
            await self._call_with_retry(
                self._app.bot.edit_message_text,
                chat_id=chat_id,
                message_id=buf.message_id,
                text=primary_html,
                parse_mode="HTML",
            )
        except BadRequest as e:
            if self._is_not_modified_error(e):
                logger.debug("[Telegram] Final stream edit already applied")
                return
            # Fall back to plain text
            primary_plain = raw_text[:TELEGRAM_MAX_MESSAGE_LEN]
            await self._call_with_retry(
                self._app.bot.edit_message_text,
                chat_id=chat_id,
                message_id=buf.message_id,
                text=primary_plain,
            )

        for extra_chunk in extra_chunks:
            await self._send_text(chat_id, extra_chunk)

    async def _edit_stream_message(
        self, chat_id: int, buf: _StreamBuf, meta: dict[str, Any]
    ) -> None:
        """Edit or create streaming message."""
        now = time.monotonic()
        thread_kwargs = {}
        if msg_thread_id := meta.get("message_thread_id"):
            thread_kwargs["message_thread_id"] = msg_thread_id

        if buf.message_id is None:
            preview = _strip_md_block(buf.text)
            sent = await self._call_with_retry(
                self._app.bot.send_message,
                chat_id=chat_id,
                text=preview,
                **thread_kwargs,
            )
            buf.message_id = sent.message_id
            buf.last_edit = now
        elif (now - buf.last_edit) >= self.config.stream_edit_interval:
            if len(buf.text) > TELEGRAM_MAX_MESSAGE_LEN:
                await self._flush_stream_overflow(chat_id, buf, thread_kwargs)
                buf.last_edit = now
                return
            preview = _strip_md_block(buf.text)
            try:
                await self._call_with_retry(
                    self._app.bot.edit_message_text,
                    chat_id=chat_id,
                    message_id=buf.message_id,
                    text=preview,
                )
                buf.last_edit = now
            except BadRequest as e:
                if self._is_not_modified_error(e):
                    buf.last_edit = now
                    return
                raise

    async def _flush_stream_overflow(
        self, chat_id: int, buf: _StreamBuf, thread_kwargs: dict
    ) -> None:
        """Split oversized stream buffer."""
        chunks = split_message(buf.text, TELEGRAM_MAX_MESSAGE_LEN)
        if len(chunks) <= 1:
            return
        await self._call_with_retry(
            self._app.bot.edit_message_text,
            chat_id=chat_id,
            message_id=buf.message_id,
            text=chunks[0],
        )
        for chunk in chunks[1:-1]:
            await self._call_with_retry(
                self._app.bot.send_message,
                chat_id=chat_id,
                text=chunk,
                **thread_kwargs,
            )
        tail = chunks[-1]
        sent = await self._call_with_retry(
            self._app.bot.send_message,
            chat_id=chat_id,
            text=tail,
            **thread_kwargs,
        )
        buf.message_id = sent.message_id
        buf.text = tail

    async def _send_media(
        self, chat_id: int, media_path: str, reply_params: Any, thread_kwargs: dict
    ) -> None:
        """Send media file via Telegram."""
        media_type = self._get_media_type(media_path)
        sender = {
            "photo": self._app.bot.send_photo,
            "video": self._app.bot.send_video,
            "voice": self._app.bot.send_voice,
            "audio": self._app.bot.send_audio,
        }.get(media_type, self._app.bot.send_document)
        param = {
            "photo": "photo",
            "video": "video",
            "voice": "voice",
            "audio": "audio",
        }.get(media_type, "document")
        extra: dict[str, Any] = {}
        if media_type == "video":
            extra["supports_streaming"] = True

        if media_path.startswith(("http://", "https://")):
            await self._call_with_retry(
                sender,
                chat_id=chat_id,
                **{param: media_path},
                reply_parameters=reply_params,
                **thread_kwargs,
                **extra,
            )
        else:
            media_bytes = Path(media_path).read_bytes()
            filename = Path(media_path).name
            await self._call_with_retry(
                sender,
                chat_id=chat_id,
                reply_parameters=reply_params,
                **thread_kwargs,
                **extra,
                **{param: media_bytes, "filename": filename},
            )

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_params: Any = None,
        thread_kwargs: dict | None = None,
        render_as_blockquote: bool = False,
        reply_markup: Any = None,
    ) -> None:
        """Send text message with HTML formatting."""
        html = (
            _tool_hint_to_telegram_blockquote(text)
            if render_as_blockquote
            else _markdown_to_telegram_html(text)
        )
        try:
            await self._call_with_retry(
                self._app.bot.send_message,
                chat_id=chat_id,
                text=html,
                parse_mode="HTML",
                reply_parameters=reply_params,
                reply_markup=reply_markup,
                **(thread_kwargs or {}),
            )
        except BadRequest as e:
            logger.warning("[Telegram] HTML parse failed, using plain: %s", e)
            await self._call_with_retry(
                self._app.bot.send_message,
                chat_id=chat_id,
                text=text,
                reply_parameters=reply_params,
                reply_markup=reply_markup,
                **(thread_kwargs or {}),
            )

    async def _call_with_retry(self, fn, *args, **kwargs) -> Any:
        """Call Telegram API with retry on timeout."""
        from telegram.error import RetryAfter

        for attempt in range(1, _SEND_MAX_RETRIES + 1):
            try:
                return await fn(*args, **kwargs)
            except TimedOut:
                if attempt == _SEND_MAX_RETRIES:
                    raise
                delay = _SEND_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning("[Telegram] timeout, retry %d in %.1fs", attempt, delay)
                await asyncio.sleep(delay)
            except RetryAfter as e:
                if attempt == _SEND_MAX_RETRIES:
                    raise
                delay = float(e.retry_after)
                logger.warning("[Telegram] flood control, retry in %.1fs", delay)
                await asyncio.sleep(delay)

    @staticmethod
    def _is_not_modified_error(exc: Exception) -> bool:
        """Check if error is 'message not modified'."""
        return isinstance(exc, BadRequest) and "message is not modified" in str(exc).lower()

    @staticmethod
    def _get_media_type(path: str) -> str:
        """Guess media type from extension."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext in ("mp4", "mov", "avi", "mkv", "webm"):
            return "video"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    @staticmethod
    def _sender_id(user: Any) -> str:
        """Build sender_id with username."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return
        user = update.effective_user
        if not self.is_allowed(self._sender_id(user)):
            return
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm soothe.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message or not update.effective_user:
            return
        if not self.is_allowed(self._sender_id(update.effective_user)):
            return
        await update.message.reply_text(
            "Available commands:\n"
            "/start - Start the bot\n"
            "/new - Start new conversation\n"
            "/stop - Stop current task\n"
            "/status - Show status\n"
            "/help - Show this help"
        )

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash command to agent."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        sender_id = self._sender_id(user)
        if not self.is_allowed(sender_id):
            return

        content = message.text or ""
        if content.startswith("/") and "@" in content:
            cmd_part, *rest = content.split(" ", 1)
            cmd_part = cmd_part.split("@")[0]
            content = f"{cmd_part} {rest[0]}" if rest else cmd_part

        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(message.chat_id),
            content=content,
            metadata=self._build_message_metadata(message, user),
            is_dm=message.chat.type == "private",
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming message."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        sender_id = self._sender_id(user)
        chat_id = str(message.chat_id)

        if not self.is_allowed(sender_id):
            return

        if not await self._is_group_message_for_bot(message):
            return

        # Build content
        content_parts = []
        media_paths = []

        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        if message.location:
            lat = message.location.latitude
            lon = message.location.longitude
            content_parts.append(f"[location: {lat}, {lon}]")

        # Download media
        media_paths, media_parts = await self._download_message_media(message)
        content_parts.extend(media_parts)

        content = "\n".join(content_parts) if content_parts else "[empty message]"

        self._start_typing(chat_id)
        await self._add_reaction(chat_id, message.message_id, self.config.react_emoji)

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media_paths,
            metadata=self._build_message_metadata(message, user),
            is_dm=message.chat.type == "private",
        )

    async def _download_message_media(self, msg: Any) -> tuple[list[str], list[str]]:
        """Download media from message."""
        media_file = None
        media_type = None
        if getattr(msg, "photo", None):
            media_file = msg.photo[-1]
            media_type = "image"
        elif getattr(msg, "voice", None):
            media_file = msg.voice
            media_type = "voice"
        elif getattr(msg, "audio", None):
            media_file = msg.audio
            media_type = "audio"
        elif getattr(msg, "document", None):
            media_file = msg.document
            media_type = "file"
        elif getattr(msg, "video", None):
            media_file = msg.video
            media_type = "video"

        if not media_file or not self._app:
            return [], []

        try:
            file = await self._app.bot.get_file(media_file.file_id)
            # Create temp file path
            import tempfile

            ext = self._get_extension(media_type, getattr(media_file, "mime_type", None))
            fd, path = tempfile.mkstemp(suffix=ext, prefix="telegram_")
            Path(path).write_bytes(await file.download_to_drive())
            return [path], [f"[{media_type}: {path}]"]
        except Exception as e:
            logger.warning("[Telegram] Failed to download media: %s", e)
            return [], []

    def _get_extension(self, media_type: str, mime_type: str | None) -> str:
        """Get file extension from media type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "audio/ogg": ".ogg",
                "audio/mpeg": ".mp3",
                "video/mp4": ".mp4",
                "video/webm": ".webm",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]
        return {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "video": ".mp4"}.get(
            media_type, ""
        )

    async def _is_group_message_for_bot(self, message: Any) -> bool:
        """Check if group message targets the bot."""
        if message.chat.type == "private" or self.config.group_policy == "open":
            return True
        bot_id, bot_username = await self._ensure_bot_identity()
        if bot_username:
            text = message.text or ""
            if f"@{bot_username}" in text.lower():
                return True
        reply_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        return bool(bot_id and reply_user and reply_user.id == bot_id)

    async def _ensure_bot_identity(self) -> tuple[int | None, str | None]:
        """Get bot identity."""
        if self._bot_user_id is not None:
            return self._bot_user_id, self._bot_username
        if not self._app:
            return None, None
        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        return self._bot_user_id, self._bot_username

    @staticmethod
    def _build_message_metadata(message: Any, user: Any) -> dict[str, Any]:
        """Build message metadata."""
        return {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": message.chat.type != "private",
        }

    def _start_typing(self, chat_id: str) -> None:
        """Start typing indicator."""
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop typing indicator."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Send typing action periodically."""
        with suppress(asyncio.CancelledError):
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)

    async def _add_reaction(self, chat_id: str, message_id: int, emoji: str) -> None:
        """Add emoji reaction."""
        if not self._app or not emoji:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
        except Exception as e:
            logger.debug("[Telegram] reaction failed: %s", e)

    async def _remove_reaction(self, chat_id: str, message_id: int) -> None:
        """Remove emoji reaction."""
        if not self._app:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=message_id,
                reaction=[],
            )
        except Exception as e:
            logger.debug("[Telegram] reaction removal failed: %s", e)

    async def _on_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline keyboard callback."""
        if not update.callback_query or not update.effective_user:
            return
        query = update.callback_query
        user = update.effective_user
        chat_id = query.message.chat_id if query.message else None
        sender_id = self._sender_id(user)
        if not chat_id or not self.is_allowed(sender_id):
            return
        button_label = query.data or ""
        await query.answer()
        self._start_typing(str(chat_id))
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str(chat_id),
            content=button_label,
            metadata={"callback_query_id": query.id, "button_label": button_label},
            is_dm=True,
        )

    def _build_keyboard(self, buttons: list[list[str]]) -> InlineKeyboardMarkup | None:
        """Build inline keyboard."""
        if not buttons or not self.config.inline_keyboards:
            return None
        keyboard = [
            [InlineKeyboardButton(label, callback_data=label[:64]) for label in row]
            for row in buttons
        ]
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def _buttons_as_text(buttons: list[list[str]]) -> str:
        """Render buttons as text fallback."""
        return "\n".join(" ".join(f"[{label}]" for label in row) for row in buttons if row)

    def _on_polling_error(self, exc: Exception) -> None:
        """Handle polling error."""
        if isinstance(exc, (NetworkError, TimedOut)):
            logger.warning("[Telegram] polling network issue: %s", exc)
        else:
            logger.error("[Telegram] polling error: %s", exc)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle Telegram error."""
        if isinstance(context.error, (NetworkError, TimedOut)):
            logger.warning("[Telegram] network issue: %s", context.error)
        else:
            logger.error("[Telegram] error: %s", context.error)
