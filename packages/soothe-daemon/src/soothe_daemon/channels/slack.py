"""Slack channel implementation using Socket Mode.

Migrated from nanoBot with adaptations for soothe-daemon Channel architecture (RFC-620).
"""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.websockets import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slackify_markdown import slackify_markdown

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.platform_helpers import safe_filename, split_message

logger = logging.getLogger(__name__)

# Slack limits
SLACK_MAX_MESSAGE_LEN = 39_000
SLACK_DOWNLOAD_TIMEOUT = 30.0
SLACK_SOCKET_CONNECT_TIMEOUT_S = 45.0
_HTML_DOWNLOAD_PREFIXES = (b"<!doctype html", b"<html")


class SlackDMConfig:
    """Slack DM policy configuration."""

    enabled: bool = True
    policy: str = "open"
    allow_from: list[str] = []

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


class SlackConfig:
    """Slack channel configuration."""

    enabled: bool = False
    mode: str = "socket"
    bot_token: str = ""
    app_token: str = ""
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    done_emoji: str = "white_check_mark"
    include_thread_context: bool = True
    thread_context_limit: int = 20
    allow_from: list[str] = []
    group_policy: str = "mention"
    group_allow_from: list[str] = []
    dm: SlackDMConfig = None  # type: ignore[assignment]

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        if self.dm is None:
            self.dm = SlackDMConfig()


class SlackChannel(Channel):
    """Slack channel using Socket Mode.

    Implements RFC-620 Channel interface with streaming support.
    """

    name = "slack"
    display_name = "Slack"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = True

    _SLACK_ID_RE = re.compile(r"^[CDGUW][A-Z0-9]{2,}$")
    _SLACK_CHANNEL_REF_RE = re.compile(r"^<#([A-Z0-9]+)(?:\|[^>]+)?>$")
    _SLACK_USER_REF_RE = re.compile(r"^<@([A-Z0-9]+)(?:\|[^>]+)?>$")
    _THREAD_CONTEXT_CACHE_LIMIT = 10_000

    # Markdown conversion patterns
    _TABLE_RE = re.compile(r"(?m)^\|.*\|$(?:\n\|[\s:|-]*\|$)(?:\n\|.*\|$)*")
    _CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_RE = re.compile(r"`[^`]+`")
    _LEFTOVER_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
    _LEFTOVER_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    _BARE_URL_RE = re.compile(r"(?<![|<])(https?://\S+)")

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "mode": "socket",
            "bot_token": "",
            "app_token": "",
            "reply_in_thread": True,
            "streaming": True,
        }

    def __init__(self, config: Any, manager: Any) -> None:
        """Initialize Slack channel.

        Args:
            config: Slack configuration.
            manager: ChannelManager for inbound routing.
        """
        super().__init__(config, manager)
        if isinstance(config, dict):
            self.config = SlackConfig(**config)
        else:
            self.config = config
        self._web_client: AsyncWebClient | None = None
        self._socket_client: SocketModeClient | None = None
        self._bot_user_id: str | None = None
        self._target_cache: dict[str, str] = {}
        self._thread_context_attempted: set[str] = set()

    async def start(self) -> None:
        """Start the Slack Socket Mode client."""
        if not self.config.bot_token or not self.config.app_token:
            logger.error("[Slack] bot/app token not configured")
            return
        if self.config.mode != "socket":
            logger.error("[Slack] Unsupported mode: %s", self.config.mode)
            return

        self._running = True

        self._web_client = AsyncWebClient(token=self.config.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self._web_client,
        )

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)

        # Resolve bot user ID
        try:
            auth = await self._web_client.auth_test()
            self._bot_user_id = auth.get("user_id")
            logger.info("[Slack] Bot connected as %s", self._bot_user_id)
        except Exception as e:
            logger.warning("[Slack] auth_test failed: %s", e)

        logger.info("[Slack] Starting Socket Mode client...")
        try:
            await asyncio.wait_for(
                self._socket_client.connect(),
                timeout=SLACK_SOCKET_CONNECT_TIMEOUT_S,
            )
        except TimeoutError:
            logger.error("[Slack] Socket Mode WebSocket handshake timed out")
            await self.stop()
            raise RuntimeError("Slack Socket Mode WebSocket connect timed out")

        logger.info("[Slack] Socket Mode WebSocket connected")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the Slack client."""
        self._running = False
        if self._socket_client:
            try:
                await self._socket_client.close()
            except Exception as e:
                logger.warning("[Slack] Socket close failed: %s", e)
            self._socket_client = None

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send a message through Slack.

        Args:
            chat_id: Slack channel/user ID.
            message: ChannelMessage to send.
        """
        if not self._web_client:
            logger.warning("[Slack] Client not running")
            return

        try:
            target_chat_id = await self._resolve_target_chat_id(chat_id)
            slack_meta = message.metadata.get("slack", {}) if message.metadata else {}
            thread_ts = slack_meta.get("thread_ts")
            origin_chat_id = str((slack_meta.get("event", {}) or {}).get("channel") or chat_id)
            thread_ts_param = thread_ts if thread_ts and target_chat_id == origin_chat_id else None

            is_progress = message.is_progress()
            if not is_progress and (message.content or not message.media):
                mrkdwn = self._to_mrkdwn(message.content) if message.content else " "
                buttons = message.buttons
                chunks = split_message(mrkdwn, SLACK_MAX_MESSAGE_LEN)
                for index, chunk in enumerate(chunks):
                    kwargs: dict[str, Any] = dict(
                        channel=target_chat_id,
                        text=chunk,
                        thread_ts=thread_ts_param,
                    )
                    if buttons and index == len(chunks) - 1:
                        kwargs["blocks"] = self._build_button_blocks(chunk, buttons)
                    await self._web_client.chat_postMessage(**kwargs)

            for media_path in message.media or []:
                try:
                    await self._web_client.files_upload_v2(
                        channel=target_chat_id,
                        file=media_path,
                        thread_ts=thread_ts_param,
                    )
                except Exception:
                    logger.exception("[Slack] Failed to upload file %s", media_path)

            # Update reaction emoji
            if not is_progress:
                event = slack_meta.get("event", {})
                await self._update_react_emoji(origin_chat_id, event.get("ts"))

        except Exception:
            logger.exception("[Slack] Error sending message")
            raise

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Stream incremental text via Slack message updates."""
        # Slack doesn't support true streaming, so we skip this
        # Real implementation would require message editing
        pass

    async def _resolve_target_chat_id(self, target: str) -> str:
        """Resolve human-friendly Slack targets to concrete IDs."""
        if not self._web_client:
            return target

        target = target.strip()
        if not target:
            return target

        if match := self._SLACK_CHANNEL_REF_RE.fullmatch(target):
            return match.group(1)
        if match := self._SLACK_USER_REF_RE.fullmatch(target):
            return await self._open_dm_for_user(match.group(1))
        if self._SLACK_ID_RE.fullmatch(target):
            if target.startswith(("U", "W")):
                return await self._open_dm_for_user(target)
            return target

        if target.startswith("#"):
            return await self._resolve_channel_name(target[1:])
        if target.startswith("@"):
            return await self._resolve_user_handle(target[1:])

        try:
            return await self._resolve_channel_name(target)
        except ValueError:
            return await self._resolve_user_handle(target)

    async def _resolve_channel_name(self, name: str) -> str:
        """Resolve channel name to ID."""
        normalized = self._normalize_target_name(name)
        if not normalized:
            raise ValueError("Slack target channel name is empty")

        cache_key = f"channel:{normalized}"
        if cache_key in self._target_cache:
            return self._target_cache[cache_key]

        cursor: str | None = None
        while True:
            response = await self._web_client.conversations_list(
                types="public_channel,private_channel",
                exclude_archived=True,
                limit=200,
                cursor=cursor,
            )
            for channel in response.get("channels", []):
                if self._normalize_target_name(str(channel.get("name") or "")) == normalized:
                    channel_id = str(channel.get("id") or "")
                    if channel_id:
                        self._target_cache[cache_key] = channel_id
                        return channel_id
            cursor = ((response.get("response_metadata") or {}).get("next_cursor") or "").strip()
            if not cursor:
                break

        raise ValueError(f"Slack channel '{name}' not found")

    async def _resolve_user_handle(self, handle: str) -> str:
        """Resolve user handle to DM channel ID."""
        normalized = self._normalize_target_name(handle)
        if not normalized:
            raise ValueError("Slack target user handle is empty")

        cache_key = f"user:{normalized}"
        if cache_key in self._target_cache:
            return self._target_cache[cache_key]

        cursor: str | None = None
        while True:
            response = await self._web_client.users_list(limit=200, cursor=cursor)
            for member in response.get("members", []):
                if self._member_matches_handle(member, normalized):
                    user_id = str(member.get("id") or "")
                    if not user_id:
                        continue
                    dm_id = await self._open_dm_for_user(user_id)
                    self._target_cache[cache_key] = dm_id
                    return dm_id
            cursor = ((response.get("response_metadata") or {}).get("next_cursor") or "").strip()
            if not cursor:
                break

        raise ValueError(f"Slack user '{handle}' not found")

    async def _open_dm_for_user(self, user_id: str) -> str:
        """Open DM channel for user."""
        response = await self._web_client.conversations_open(users=user_id)
        channel_id = str(((response.get("channel") or {}).get("id")) or "")
        if not channel_id:
            raise ValueError(f"Slack DM for user '{user_id}' could not be opened")
        return channel_id

    @staticmethod
    def _normalize_target_name(value: str) -> str:
        return value.strip().lstrip("#@").lower()

    @classmethod
    def _member_matches_handle(cls, member: dict[str, Any], normalized: str) -> bool:
        profile = member.get("profile") or {}
        candidates = {
            str(member.get("name") or ""),
            str(profile.get("display_name") or ""),
            str(profile.get("display_name_normalized") or ""),
            str(profile.get("real_name") or ""),
            str(profile.get("real_name_normalized") or ""),
        }
        return normalized in {cls._normalize_target_name(c) for c in candidates if c}

    async def _on_socket_request(self, client: SocketModeClient, req: SocketModeRequest) -> None:
        """Handle incoming Socket Mode requests."""
        if req.type == "interactive":
            await self._on_block_action(client, req)
            return
        if req.type != "events_api":
            return

        # Acknowledge
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        payload = req.payload or {}
        event = payload.get("event") or {}
        event_type = event.get("type")

        if event_type not in ("message", "app_mention"):
            return

        sender_id = event.get("user")
        chat_id = event.get("channel")

        subtype = event.get("subtype")
        if subtype and subtype != "file_share":
            return
        if self._bot_user_id and sender_id == self._bot_user_id:
            return

        text = event.get("text") or ""
        if event_type == "message" and self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            return

        if not sender_id or not chat_id:
            return

        channel_type = event.get("channel_type") or ""

        if not self._is_allowed(sender_id, chat_id, channel_type):
            return

        if channel_type != "im" and not self._should_respond_in_channel(event_type, text, chat_id):
            return

        text = self._strip_bot_mention(text)

        event_ts = event.get("ts")
        raw_thread_ts = event.get("thread_ts")
        thread_ts = raw_thread_ts
        if self.config.reply_in_thread and not thread_ts and channel_type != "im":
            thread_ts = event_ts

        # Add reaction
        try:
            if self._web_client and event.get("ts"):
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name=self.config.react_emoji,
                    timestamp=event.get("ts"),
                )
        except Exception as e:
            logger.debug("[Slack] reactions_add failed: %s", e)

        # Download files
        media_paths: list[str] = []
        file_markers: list[str] = []
        for file_info in event.get("files") or []:
            if not isinstance(file_info, dict):
                continue
            file_path, marker = await self._download_slack_file(file_info)
            if file_path:
                media_paths.append(file_path)
            if marker:
                file_markers.append(marker)

        content = await self._with_thread_context(
            text,
            chat_id=chat_id,
            channel_type=channel_type,
            thread_ts=thread_ts,
            raw_thread_ts=raw_thread_ts,
            current_ts=event_ts,
        )
        if file_markers:
            content = "\n".join(part for part in [content, *file_markers] if part)
        if not content and not media_paths:
            return

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=content,
            media=media_paths,
            metadata={
                "slack": {
                    "event": event,
                    "thread_ts": thread_ts,
                    "channel_type": channel_type,
                },
            },
        )

    async def _download_slack_file(self, file_info: dict[str, Any]) -> tuple[str | None, str]:
        """Download Slack file."""
        file_id = str(file_info.get("id") or "file")
        name = str(
            file_info.get("name") or file_info.get("title") or file_info.get("id") or "slack-file"
        )
        marker_type = (
            "image" if str(file_info.get("mimetype") or "").startswith("image/") else "file"
        )
        marker = f"[{marker_type}: {name}]"
        url = str(file_info.get("url_private_download") or file_info.get("url_private") or "")
        if not url or not self.config.bot_token:
            return None, f"[{marker_type}: {name} - unavailable]"

        filename = safe_filename(f"{file_id}_{name}")
        fd, path = tempfile.mkstemp(suffix=filename, prefix="slack_")
        try:
            async with httpx.AsyncClient(
                timeout=SLACK_DOWNLOAD_TIMEOUT, follow_redirects=True
            ) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {self.config.bot_token}"},
                )
                response.raise_for_status()
            if self._looks_like_html_download(response):
                raise ValueError("Slack returned HTML")
            Path(path).write_bytes(response.content)
            return path, marker
        except Exception as e:
            logger.warning("[Slack] Failed to download file %s: %s", file_id, e)
            return None, f"[{marker_type}: {name} - download failed]"

    @staticmethod
    def _looks_like_html_download(response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            return True
        preview = response.content[:256].lstrip().lower()
        return preview.startswith(_HTML_DOWNLOAD_PREFIXES)

    async def _on_block_action(self, client: SocketModeClient, req: SocketModeRequest) -> None:
        """Handle button clicks."""
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        payload = req.payload or {}
        actions = payload.get("actions") or []
        if not actions:
            return
        value = str(actions[0].get("value") or "")
        user_info = payload.get("user") or {}
        sender_id = str(user_info.get("id") or "")
        channel_info = payload.get("channel") or {}
        chat_id = str(channel_info.get("id") or "")
        if not sender_id or not chat_id or not value:
            return
        message_info = payload.get("message") or {}
        thread_ts = message_info.get("thread_ts") or message_info.get("ts")
        channel_type = self._infer_channel_type(chat_id)
        if not self._is_allowed(sender_id, chat_id, channel_type):
            return

        await self._handle_message(
            sender_id=sender_id,
            chat_id=chat_id,
            content=value,
            metadata={"slack": {"thread_ts": thread_ts, "channel_type": channel_type}},
        )

    async def _with_thread_context(
        self,
        text: str,
        *,
        chat_id: str,
        channel_type: str,
        thread_ts: str | None,
        raw_thread_ts: str | None,
        current_ts: str | None,
    ) -> str:
        """Include thread history."""
        del channel_type
        if (
            not self.config.include_thread_context
            or not self._web_client
            or not raw_thread_ts
            or not thread_ts
            or current_ts == thread_ts
        ):
            return text

        key = f"{chat_id}:{thread_ts}"
        if key in self._thread_context_attempted:
            return text
        if len(self._thread_context_attempted) >= self._THREAD_CONTEXT_CACHE_LIMIT:
            self._thread_context_attempted.clear()
        self._thread_context_attempted.add(key)

        try:
            response = await self._web_client.conversations_replies(
                channel=chat_id,
                ts=thread_ts,
                limit=max(1, self.config.thread_context_limit),
            )
        except Exception as e:
            logger.warning("[Slack] Thread context unavailable: %s", e)
            return text

        lines = self._format_thread_context(
            response.get("messages", []),
            current_ts=current_ts,
        )
        if not lines:
            return text
        return (
            "Slack thread context before this mention:\n"
            + "\n".join(lines)
            + f"\n\nCurrent message:\n{text}"
        )

    def _format_thread_context(
        self, messages: list[dict[str, Any]], *, current_ts: str | None
    ) -> list[str]:
        """Format thread messages."""
        lines: list[str] = []
        for item in messages:
            if item.get("ts") == current_ts:
                continue
            if item.get("subtype"):
                continue
            sender = str(item.get("user") or item.get("bot_id") or "unknown")
            is_bot = self._bot_user_id is not None and sender == self._bot_user_id
            label = "bot" if is_bot else f"<@{sender}>"
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            text = self._strip_bot_mention(text)
            if len(text) > 500:
                text = text[:500] + "…"
            lines.append(f"- {label}: {text}")
        return lines

    @staticmethod
    def _build_button_blocks(text: str, buttons: list[list[str]]) -> list[dict[str, Any]]:
        """Build Slack Block Kit blocks."""
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": text[:3000]}},
        ]
        elements = []
        for row in buttons:
            for label in row:
                elements.append(
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": label[:75]},
                        "value": label[:75],
                        "action_id": f"btn_{label[:50]}",
                    }
                )
        if elements:
            blocks.append({"type": "actions", "elements": elements[:25]})
        return blocks

    async def _update_react_emoji(self, chat_id: str, ts: str | None) -> None:
        """Update reaction emoji."""
        if not self._web_client or not ts:
            return
        try:
            await self._web_client.reactions_remove(
                channel=chat_id,
                name=self.config.react_emoji,
                timestamp=ts,
            )
        except Exception as e:
            logger.debug("[Slack] reactions_remove failed: %s", e)
        if self.config.done_emoji:
            try:
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name=self.config.done_emoji,
                    timestamp=ts,
                )
            except Exception as e:
                logger.debug("[Slack] Done reaction failed: %s", e)

    def _is_allowed(self, sender_id: str, chat_id: str, channel_type: str) -> bool:
        """Check if sender is allowed."""
        if channel_type == "im":
            if not self.config.dm.enabled:
                return False
            if self.config.dm.policy == "allowlist":
                return sender_id in self.config.dm.allow_from
            return True

        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return True

    def _should_respond_in_channel(self, event_type: str, text: str, chat_id: str) -> bool:
        """Check if should respond in channel."""
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            if event_type == "app_mention":
                return True
            return self._bot_user_id is not None and f"<@{self._bot_user_id}>" in text
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return False

    def is_allowed(self, sender_id: str) -> bool:
        """Slack uses channel-aware policy, so always return True here."""
        return True

    @staticmethod
    def _infer_channel_type(chat_id: str) -> str:
        """Infer channel type from ID."""
        if chat_id.startswith("D"):
            return "im"
        if chat_id.startswith("G"):
            return "group"
        return "channel"

    def _strip_bot_mention(self, text: str) -> str:
        """Strip bot mention from text."""
        if not text or not self._bot_user_id:
            return text
        return re.sub(rf"<@{re.escape(self._bot_user_id)}>\s*", "", text).strip()

    @classmethod
    def _to_mrkdwn(cls, text: str) -> str:
        """Convert Markdown to Slack mrkdwn."""
        if not text:
            return ""
        text = cls._TABLE_RE.sub(cls._convert_table, text)
        return cls._fixup_mrkdwn(slackify_markdown(text)).rstrip("\n")

    @classmethod
    def _fixup_mrkdwn(cls, text: str) -> str:
        """Fix markdown artifacts."""
        code_blocks: list[str] = []

        def _save_code(m: re.Match) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CB{len(code_blocks) - 1}\x00"

        text = cls._CODE_FENCE_RE.sub(_save_code, text)
        text = cls._INLINE_CODE_RE.sub(_save_code, text)
        text = cls._LEFTOVER_BOLD_RE.sub(r"*\1*", text)
        text = cls._LEFTOVER_HEADER_RE.sub(r"*\1*", text)
        text = cls._BARE_URL_RE.sub(lambda m: m.group(0).replace("&amp;", "&"), text)

        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)
        return text

    @staticmethod
    def _convert_table(match: re.Match) -> str:
        """Convert Markdown table to Slack-readable list."""
        lines = [ln.strip() for ln in match.group(0).strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return match.group(0)
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        start = 2 if re.fullmatch(r"[|\s:\-]+", lines[1]) else 1
        rows: list[str] = []
        for line in lines[start:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = (cells + [""] * len(headers))[: len(headers)]
            parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers)) if cells[i]]
            if parts:
                rows.append(" · ".join(parts))
        return "\n".join(rows)


__all__ = ["SlackChannel", "SlackConfig"]
