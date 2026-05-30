"""Matrix (Element) channel — inbound sync + outbound message/media delivery.

Migrated from nanoBot with adaptations for soothe-daemon channel architecture.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import time
from contextlib import suppress
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, TypeAlias

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage
from soothe_daemon.channels.platform_helpers import safe_filename

try:
    import nh3
    from mistune import create_markdown
    from nio import (
        AsyncClient,
        AsyncClientConfig,
        DownloadError,
        InviteEvent,
        JoinError,
        LoginResponse,
        MatrixRoom,
        MemoryDownloadResponse,
        RoomEncryptedMedia,
        RoomMessage,
        RoomMessageMedia,
        RoomMessageText,
        RoomSendError,
        RoomSendResponse,
        RoomTypingError,
        SyncError,
        UploadError,
    )
    from nio.crypto.attachments import decrypt_attachment
    from nio.exceptions import EncryptionError
except ImportError as e:
    raise ImportError(
        "Matrix dependencies not installed. Run: pip install matrix-nio mistune nh3"
    ) from e


logger = getLogger(__name__)

TYPING_NOTICE_TIMEOUT_MS = 30_000
# Must stay below TYPING_NOTICE_TIMEOUT_MS so the indicator doesn't expire mid-processing.
TYPING_KEEPALIVE_INTERVAL_MS = 20_000
MATRIX_HTML_FORMAT = "org.matrix.custom.html"
_ATTACH_MARKER = "[attachment: {}]"
_ATTACH_TOO_LARGE = "[attachment: {} - too large]"
_ATTACH_FAILED = "[attachment: {} - download failed]"
_ATTACH_UPLOAD_FAILED = "[attachment: {} - upload failed]"
_DEFAULT_ATTACH_NAME = "attachment"
_MSGTYPE_MAP = {"m.image": "image", "m.audio": "audio", "m.video": "video", "m.file": "file"}

MATRIX_MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)
MatrixMediaEvent: TypeAlias = RoomMessageMedia | RoomEncryptedMedia

MATRIX_MARKDOWN = create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "url", "superscript", "subscript"],
)

MATRIX_ALLOWED_HTML_TAGS = {
    "p",
    "a",
    "strong",
    "em",
    "del",
    "code",
    "pre",
    "blockquote",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "br",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "caption",
    "sup",
    "sub",
    "img",
}
MATRIX_ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"},
    "code": {"class"},
    "ol": {"start"},
    "img": {"src", "alt", "title", "width", "height"},
}
MATRIX_ALLOWED_URL_SCHEMES = {"https", "http", "matrix", "mailto", "mxc"}


def _filter_matrix_html_attribute(tag: str, attr: str, value: str) -> str | None:
    """Filter attribute values to a safe Matrix-compatible subset."""
    if tag == "a" and attr == "href":
        return (
            value
            if value.lower().startswith(("https://", "http://", "matrix:", "mailto:"))
            else None
        )
    if tag == "img" and attr == "src":
        return value if value.lower().startswith("mxc://") else None
    if tag == "code" and attr == "class":
        classes = [
            c for c in value.split() if c.startswith("language-") and not c.startswith("language-_")
        ]
        return " ".join(classes) if classes else None
    return value


MATRIX_HTML_CLEANER = nh3.Cleaner(
    tags=MATRIX_ALLOWED_HTML_TAGS,
    attributes=MATRIX_ALLOWED_HTML_ATTRIBUTES,
    attribute_filter=_filter_matrix_html_attribute,
    url_schemes=MATRIX_ALLOWED_URL_SCHEMES,
    strip_comments=True,
    link_rel="noopener noreferrer",
)


@dataclass
class _StreamBuf:
    """Buffer for managing LLM response stream data.

    Attributes:
        text: Stores the text content of the buffer.
        event_id: Identifier for the associated event. None indicates no
            specific event association.
        last_edit: Timestamp of the most recent edit to the buffer.
    """

    text: str = ""
    event_id: str | None = None
    last_edit: float = 0.0


class MatrixConfig:
    """Matrix (Element) channel configuration.

    Simple config class without Pydantic inheritance for soothe-daemon.
    """

    def __init__(
        self,
        enabled: bool = False,
        homeserver: str = "https://matrix.org",
        user_id: str = "",
        password: str = "",
        access_token: str = "",
        device_id: str = "",
        e2ee_enabled: bool = True,
        sync_stop_grace_seconds: int = 2,
        max_media_bytes: int = 20 * 1024 * 1024,
        allow_from: list[str] | None = None,
        group_policy: Literal["open", "mention", "allowlist"] = "open",
        group_allow_from: list[str] | None = None,
        allow_room_mentions: bool = False,
        streaming: bool = False,
    ) -> None:
        self.enabled = enabled
        self.homeserver = homeserver
        self.user_id = user_id
        self.password = password
        self.access_token = access_token
        self.device_id = device_id
        self.e2ee_enabled = e2ee_enabled
        self.sync_stop_grace_seconds = sync_stop_grace_seconds
        self.max_media_bytes = max_media_bytes
        self.allow_from = allow_from or []
        self.group_policy = group_policy
        self.group_allow_from = group_allow_from or []
        self.allow_room_mentions = allow_room_mentions
        self.streaming = streaming


def _render_markdown_html(text: str) -> str | None:
    """Render markdown to sanitized HTML; returns None for plain text."""
    try:
        formatted = MATRIX_HTML_CLEANER.clean(MATRIX_MARKDOWN(text)).strip()
    except Exception:
        return None
    if not formatted:
        return None
    # Skip formatted_body for plain <p>text</p> to keep payload minimal.
    if formatted.startswith("<p>") and formatted.endswith("</p>"):
        inner = formatted[3:-4]
        if "<" not in inner and ">" not in inner:
            return None
    return formatted


def _build_matrix_text_content(
    text: str,
    event_id: str | None = None,
    thread_relates_to: dict[str, object] | None = None,
) -> dict[str, object]:
    """Construct Matrix text content payload.

    Args:
        text: Plain text content.
        event_id: Optional event ID to replace (for edits).
        thread_relates_to: Optional thread relation metadata.

    Returns:
        Matrix content dictionary.
    """
    content: dict[str, object] = {"msgtype": "m.text", "body": text, "m.mentions": {}}
    if html := _render_markdown_html(text):
        content["format"] = MATRIX_HTML_FORMAT
        content["formatted_body"] = html
    if event_id:
        content["m.new_content"] = {
            "body": text,
            "msgtype": "m.text",
        }
        content["m.relates_to"] = {
            "rel_type": "m.replace",
            "event_id": event_id,
        }
        if thread_relates_to:
            content["m.new_content"]["m.relates_to"] = thread_relates_to
    elif thread_relates_to:
        content["m.relates_to"] = thread_relates_to

    return content


class MatrixChannel(Channel):
    """Matrix (Element) channel using long-polling sync.

    Supports streaming via message editing (Matrix supports in-place edits).
    """

    name = "matrix"
    display_name = "Matrix"
    supports_streaming = True  # Matrix supports streaming via message edits

    _STREAM_EDIT_INTERVAL = 2  # min seconds between edit_message_text calls
    monotonic_time = time.monotonic

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "homeserver": "https://matrix.org",
            "user_id": "",
            "password": "",
            "access_token": "",
            "device_id": "",
            "e2ee_enabled": True,
            "sync_stop_grace_seconds": 2,
            "max_media_bytes": 20 * 1024 * 1024,
            "allow_from": [],
            "group_policy": "open",
            "group_allow_from": [],
            "allow_room_mentions": False,
            "streaming": False,
        }

    def __init__(
        self,
        config: Any,
        manager: Any,
    ) -> None:
        if isinstance(config, dict):
            config = MatrixConfig(**config)
        super().__init__(config, manager)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._server_upload_limit_bytes: int | None = None
        self._server_upload_limit_checked = False
        self._stream_bufs: dict[str, _StreamBuf] = {}
        self._started_at_ms: int = 0

    def _media_dir(self) -> Path:
        """Get media storage directory for Matrix."""
        return Path.home() / ".soothe" / "media" / "matrix"

    def _data_dir(self) -> Path:
        """Get data storage directory for Matrix."""
        return Path.home() / ".soothe" / "matrix"

    async def start(self) -> None:
        """Start Matrix client and begin sync loop."""
        self._running = True
        self._started_at_ms = int(time.time() * 1000)

        self.store_path = self._data_dir() / "store"
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.session_path = self.store_path / "session.json"

        # Ensure media directory exists
        self._media_dir().mkdir(parents=True, exist_ok=True)

        # Replace ':' with '_' to produce a Windows-safe filename
        safe_store_name = self.config.user_id.replace(":", "_") + f"_{self.config.device_id}.db"

        self.client = AsyncClient(
            homeserver=self.config.homeserver,
            user=self.config.user_id,
            store_path=self.store_path,
            config=AsyncClientConfig(
                store_sync_tokens=True,
                encryption_enabled=self.config.e2ee_enabled,
                store_name=safe_store_name,
            ),
        )

        self._register_event_callbacks()
        self._register_response_callbacks()

        if not self.config.e2ee_enabled:
            logger.warning("E2EE disabled; encrypted rooms may be undecryptable.")

        if self.config.password:
            if self.config.access_token or self.config.device_id:
                logger.warning(
                    "Password-based login active; access_token and device_id fields will be ignored."
                )

            create_new_session = True
            if self.session_path.exists():
                logger.info(
                    "Found session.json at %s; attempting to use existing session",
                    self.session_path,
                )
                try:
                    with open(self.session_path, encoding="utf-8") as f:
                        session = json.load(f)
                    self.client.user_id = self.config.user_id
                    self.client.access_token = session["access_token"]
                    self.client.device_id = session["device_id"]
                    self.client.load_store()
                    logger.info("Successfully loaded from existing session")
                    create_new_session = False
                except Exception as e:
                    logger.warning("Failed to load from existing session: %s", e)
                    logger.info("Falling back to password login...")

            if create_new_session:
                logger.info("Using password login...")
                resp = await self.client.login(self.config.password)
                if isinstance(resp, LoginResponse):
                    logger.info("Logged in using a password; saving details to disk")
                    self._write_session_to_disk(resp)
                else:
                    logger.error("Failed to log in: %s", resp)
                    return

        elif self.config.access_token and self.config.device_id:
            try:
                self.client.user_id = self.config.user_id
                self.client.access_token = self.config.access_token
                self.client.device_id = self.config.device_id
                self.client.load_store()
                logger.info("Successfully loaded from existing session")
            except Exception as e:
                logger.warning("Failed to load from existing session: %s", e)

        else:
            logger.warning(
                "Unable to load a session due to missing password, access_token, or device_id; "
                "encryption may not work"
            )
            return

        self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """Stop the Matrix channel with graceful sync shutdown."""
        self._running = False
        for room_id in list(self._typing_tasks):
            await self._stop_typing_keepalive(room_id, clear_typing=False)
        if self.client:
            self.client.stop_sync_forever()
        if self._sync_task:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._sync_task),
                    timeout=self.config.sync_stop_grace_seconds,
                )
            except (TimeoutError, asyncio.CancelledError):
                self._sync_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._sync_task
        if self.client:
            await self.client.close()

    def _write_session_to_disk(self, resp: LoginResponse) -> None:
        """Save login session to disk for persistence across restarts."""
        session = {
            "access_token": resp.access_token,
            "device_id": resp.device_id,
        }
        try:
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(session, f, indent=2)
            logger.info("Session saved to %s", self.session_path)
        except Exception as e:
            logger.warning("Failed to save session: %s", e)

    def _collect_outbound_media_candidates(self, media: list[str]) -> list[Path]:
        """Deduplicate and resolve outbound attachment paths."""
        seen: set[str] = set()
        candidates: list[Path] = []
        for raw in media:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw.strip()).expanduser()
            try:
                key = str(path.resolve(strict=False))
            except OSError:
                key = str(path)
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        return candidates

    @staticmethod
    def _build_outbound_attachment_content(
        *,
        filename: str,
        mime: str,
        size_bytes: int,
        mxc_url: str,
        encryption_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build Matrix content payload for an uploaded file/image/audio/video."""
        prefix = mime.split("/")[0]
        msgtype = {"image": "m.image", "audio": "m.audio", "video": "m.video"}.get(prefix, "m.file")
        content: dict[str, Any] = {
            "msgtype": msgtype,
            "body": filename,
            "filename": filename,
            "info": {"mimetype": mime, "size": size_bytes},
            "m.mentions": {},
        }
        if encryption_info:
            content["file"] = {**encryption_info, "url": mxc_url}
        else:
            content["url"] = mxc_url
        return content

    def _is_encrypted_room(self, room_id: str) -> bool:
        """Check if room is encrypted."""
        if not self.client:
            return False
        room = getattr(self.client, "rooms", {}).get(room_id)
        return bool(getattr(room, "encrypted", False))

    async def _send_room_content(
        self, room_id: str, content: dict[str, Any]
    ) -> None | RoomSendResponse | RoomSendError:
        """Send m.room.message with E2EE options."""
        if not self.client:
            return None
        kwargs: dict[str, Any] = {
            "room_id": room_id,
            "message_type": "m.room.message",
            "content": content,
        }

        if self.config.e2ee_enabled:
            kwargs["ignore_unverified_devices"] = True
        response = await self.client.room_send(**kwargs)
        return response

    async def _resolve_server_upload_limit_bytes(self) -> int | None:
        """Query homeserver upload limit once per channel lifecycle."""
        if self._server_upload_limit_checked:
            return self._server_upload_limit_bytes
        self._server_upload_limit_checked = True
        if not self.client:
            return None
        try:
            response = await self.client.content_repository_config()
        except Exception:
            logger.error("Failed to fetch server upload limit", exc_info=True)
            return None
        upload_size = getattr(response, "upload_size", None)
        if isinstance(upload_size, int) and upload_size > 0:
            self._server_upload_limit_bytes = upload_size
            return upload_size
        return None

    async def _effective_media_limit_bytes(self) -> int:
        """min(local config, server advertised) — 0 blocks all uploads."""
        local_limit = max(int(self.config.max_media_bytes), 0)
        server_limit = await self._resolve_server_upload_limit_bytes()
        if server_limit is None:
            return local_limit
        return min(local_limit, server_limit) if local_limit else 0

    async def _upload_and_send_attachment(
        self,
        room_id: str,
        path: Path,
        limit_bytes: int,
        relates_to: dict[str, Any] | None = None,
    ) -> str | None:
        """Upload one local file to Matrix and send it as a media message.

        Returns failure marker or None on success.
        """
        if not self.client:
            return _ATTACH_UPLOAD_FAILED.format(path.name or _DEFAULT_ATTACH_NAME)

        resolved = path.expanduser().resolve(strict=False)
        filename = safe_filename(resolved.name) or _DEFAULT_ATTACH_NAME
        fail = _ATTACH_UPLOAD_FAILED.format(filename)

        if not resolved.is_file():
            return fail
        try:
            size_bytes = resolved.stat().st_size
        except OSError:
            return fail
        if limit_bytes <= 0 or size_bytes > limit_bytes:
            return _ATTACH_TOO_LARGE.format(filename)

        mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"
        try:
            with resolved.open("rb") as f:
                upload_result = await self.client.upload(
                    f,
                    content_type=mime,
                    filename=filename,
                    encrypt=self.config.e2ee_enabled and self._is_encrypted_room(room_id),
                    filesize=size_bytes,
                )
        except Exception:
            logger.error("Matrix media upload failed for %s", filename, exc_info=True)
            return fail

        upload_response = upload_result[0] if isinstance(upload_result, tuple) else upload_result
        encryption_info = (
            upload_result[1]
            if isinstance(upload_result, tuple) and isinstance(upload_result[1], dict)
            else None
        )
        if isinstance(upload_response, UploadError):
            return fail
        mxc_url = getattr(upload_response, "content_uri", None)
        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return fail

        content = self._build_outbound_attachment_content(
            filename=filename,
            mime=mime,
            size_bytes=size_bytes,
            mxc_url=mxc_url,
            encryption_info=encryption_info,
        )
        if relates_to:
            content["m.relates_to"] = relates_to
        try:
            await self._send_room_content(room_id, content)
        except Exception:
            logger.error("Matrix room content send failed for room_id=%s", room_id, exc_info=True)
            return fail
        return None

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send outbound content; clear typing for non-progress messages."""
        if not self.client:
            return
        text = message.content or ""
        candidates = self._collect_outbound_media_candidates(message.media)
        relates_to = self._build_thread_relates_to(message.metadata)
        is_progress = bool((message.metadata or {}).get("_progress"))
        try:
            failures: list[str] = []
            if candidates:
                limit_bytes = await self._effective_media_limit_bytes()
                for path in candidates:
                    if fail := await self._upload_and_send_attachment(
                        room_id=chat_id,
                        path=path,
                        limit_bytes=limit_bytes,
                        relates_to=relates_to,
                    ):
                        failures.append(fail)
            if failures:
                text = (
                    f"{text.rstrip()}\n{chr(10).join(failures)}"
                    if text.strip()
                    else "\n".join(failures)
                )
            if text.strip():
                content = _build_matrix_text_content(text)
                if relates_to:
                    content["m.relates_to"] = relates_to
                await self._send_room_content(chat_id, content)
        finally:
            if not is_progress:
                await self._stop_typing_keepalive(chat_id, clear_typing=True)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None
    ) -> None:
        """Stream incremental text chunk via message editing."""
        meta = metadata or {}
        relates_to = self._build_thread_relates_to(metadata)

        if meta.get("_stream_end"):
            buf = self._stream_bufs.pop(chat_id, None)
            if not buf or not buf.event_id or not buf.text:
                return

            await self._stop_typing_keepalive(chat_id, clear_typing=True)

            content = _build_matrix_text_content(
                buf.text,
                buf.event_id,
                thread_relates_to=relates_to,
            )
            await self._send_room_content(chat_id, content)
            return

        buf = self._stream_bufs.get(chat_id)
        if buf is None:
            buf = _StreamBuf()
            self._stream_bufs[chat_id] = buf
        buf.text += delta

        if not buf.text.strip():
            return

        now = self.monotonic_time()

        if not buf.last_edit or (now - buf.last_edit) >= self._STREAM_EDIT_INTERVAL:
            try:
                content = _build_matrix_text_content(
                    buf.text,
                    buf.event_id,
                    thread_relates_to=relates_to,
                )
                response = await self._send_room_content(chat_id, content)
                buf.last_edit = now
                if not buf.event_id and response:
                    # We are editing the same message all the time,
                    # so only the first time the event id needs to be set
                    buf.event_id = getattr(response, "event_id", None)
            except Exception:
                logger.error("Stream send/edit failed for chat_id=%s", chat_id, exc_info=True)
                await self._stop_typing_keepalive(chat_id, clear_typing=True)

    def _register_event_callbacks(self) -> None:
        """Register Matrix event callbacks."""
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_media_message, MATRIX_MEDIA_EVENT_FILTER)
        self.client.add_event_callback(self._on_room_invite, InviteEvent)

    def _register_response_callbacks(self) -> None:
        """Register Matrix response callbacks."""
        self.client.add_response_callback(self._on_sync_error, SyncError)
        self.client.add_response_callback(self._on_join_error, JoinError)
        self.client.add_response_callback(self._on_send_error, RoomSendError)

    def _is_fatal_auth_response(self, response: Any) -> bool:
        """Check if response indicates fatal authentication error."""
        code = getattr(response, "status_code", None)
        is_auth = code in {"M_UNKNOWN_TOKEN", "M_FORBIDDEN", "M_UNAUTHORIZED"}
        return is_auth or bool(getattr(response, "soft_logout", False))

    def _log_response_error(self, label: str, response: Any) -> None:
        """Log Matrix response errors — auth errors at ERROR level, rest at WARNING."""
        is_fatal = self._is_fatal_auth_response(response)
        (logger.error if is_fatal else logger.warning)("%s failed: %s", label, response)

    async def _on_sync_error(self, response: SyncError) -> None:
        """Handle sync errors."""
        self._log_response_error("sync", response)
        if self._is_fatal_auth_response(response):
            # Auth errors won't recover by retry; stop the sync loop instead of
            # spamming the homeserver every 2s.
            logger.error("Authentication failed irrecoverably; stopping sync loop")
            self._running = False
            if self.client:
                with suppress(Exception):
                    self.client.stop_sync_forever()

    async def _on_join_error(self, response: JoinError) -> None:
        """Handle join errors."""
        self._log_response_error("join", response)

    async def _on_send_error(self, response: RoomSendError) -> None:
        """Handle send errors."""
        self._log_response_error("send", response)

    async def _set_typing(self, room_id: str, typing: bool) -> None:
        """Best-effort typing indicator update."""
        if not self.client:
            return
        with suppress(Exception):
            response = await self.client.room_typing(
                room_id=room_id,
                typing_state=typing,
                timeout=TYPING_NOTICE_TIMEOUT_MS,
            )
            if isinstance(response, RoomTypingError):
                logger.debug("typing failed for %s: %s", room_id, response)

    async def _start_typing_keepalive(self, room_id: str) -> None:
        """Start periodic typing refresh (spec-recommended keepalive)."""
        await self._stop_typing_keepalive(room_id, clear_typing=False)
        await self._set_typing(room_id, True)
        if not self._running:
            return

        async def loop() -> None:
            with suppress(asyncio.CancelledError):
                while self._running:
                    await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_MS / 1000)
                    await self._set_typing(room_id, True)

        self._typing_tasks[room_id] = asyncio.create_task(loop())

    async def _stop_typing_keepalive(self, room_id: str, *, clear_typing: bool) -> None:
        """Stop typing keepalive task."""
        if task := self._typing_tasks.pop(room_id, None):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if clear_typing:
            await self._set_typing(room_id, False)

    async def _sync_loop(self) -> None:
        """Run Matrix sync loop with exponential backoff."""
        backoff = 2.0
        while self._running:
            try:
                await self.client.sync_forever(timeout=30000, full_state=True)
                backoff = 2.0
            except asyncio.CancelledError:
                break
            except Exception:
                if not self._running:
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _on_room_invite(self, room: MatrixRoom, event: InviteEvent) -> None:
        """Handle room invite."""
        if self.is_allowed(event.sender):
            await self.client.join(room.room_id)

    def _is_direct_room(self, room: MatrixRoom) -> bool:
        """Check if room is a direct message."""
        count = getattr(room, "member_count", None)
        return isinstance(count, int) and count <= 2

    def _is_bot_mentioned(self, event: RoomMessage) -> bool:
        """Check m.mentions payload for bot mention."""
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return False
        mentions = (source.get("content") or {}).get("m.mentions")
        if not isinstance(mentions, dict):
            return False
        user_ids = mentions.get("user_ids")
        if isinstance(user_ids, list) and self.config.user_id in user_ids:
            return True
        return bool(self.config.allow_room_mentions and mentions.get("room") is True)

    def _is_pre_startup_event(self, event: RoomMessage) -> bool:
        """Skip events that landed in the timeline before this process started.

        Matrix sync replays the room timeline on each startup/restart; without
        this filter old messages would be re-handled as if they were fresh.
        """
        ts = getattr(event, "server_timestamp", None)
        return isinstance(ts, int) and ts < self._started_at_ms

    def _should_process_message(self, room: MatrixRoom, event: RoomMessage) -> bool:
        """Apply sender and room policy checks."""
        if not self.is_allowed(event.sender):
            return False
        if self._is_direct_room(room):
            return True
        policy = self.config.group_policy
        if policy == "open":
            return True
        if policy == "allowlist":
            return room.room_id in (self.config.group_allow_from or [])
        if policy == "mention":
            return self._is_bot_mentioned(event)
        return False

    @staticmethod
    def _event_source_content(event: RoomMessage) -> dict[str, Any]:
        """Extract content dict from event source."""
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return {}
        content = source.get("content")
        return content if isinstance(content, dict) else {}

    def _event_thread_root_id(self, event: RoomMessage) -> str | None:
        """Get thread root event ID from event."""
        relates_to = self._event_source_content(event).get("m.relates_to")
        if not isinstance(relates_to, dict) or relates_to.get("rel_type") != "m.thread":
            return None
        root_id = relates_to.get("event_id")
        return root_id if isinstance(root_id, str) and root_id else None

    def _thread_metadata(self, event: RoomMessage) -> dict[str, str] | None:
        """Build thread metadata from event."""
        if not (root_id := self._event_thread_root_id(event)):
            return None
        meta: dict[str, str] = {"thread_root_event_id": root_id}
        if isinstance(reply_to := getattr(event, "event_id", None), str) and reply_to:
            meta["thread_reply_to_event_id"] = reply_to
        return meta

    @staticmethod
    def _build_thread_relates_to(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        """Build thread relation payload for outbound message."""
        if not metadata:
            return None
        root_id = metadata.get("thread_root_event_id")
        if not isinstance(root_id, str) or not root_id:
            return None
        reply_to = metadata.get("thread_reply_to_event_id") or metadata.get("event_id")
        if not isinstance(reply_to, str) or not reply_to:
            return None
        return {
            "rel_type": "m.thread",
            "event_id": root_id,
            "m.in_reply_to": {"event_id": reply_to},
            "is_falling_back": True,
        }

    def _event_attachment_type(self, event: MatrixMediaEvent) -> str:
        """Get attachment type from media event."""
        msgtype = self._event_source_content(event).get("msgtype")
        return _MSGTYPE_MAP.get(msgtype, "file")

    @staticmethod
    def _is_encrypted_media_event(event: MatrixMediaEvent) -> bool:
        """Check if media event is encrypted."""
        return (
            isinstance(getattr(event, "key", None), dict)
            and isinstance(getattr(event, "hashes", None), dict)
            and isinstance(getattr(event, "iv", None), str)
        )

    def _event_declared_size_bytes(self, event: MatrixMediaEvent) -> int | None:
        """Get declared size from media event."""
        info = self._event_source_content(event).get("info")
        size = info.get("size") if isinstance(info, dict) else None
        return size if isinstance(size, int) and size >= 0 else None

    def _event_mime(self, event: MatrixMediaEvent) -> str | None:
        """Get MIME type from media event."""
        info = self._event_source_content(event).get("info")
        if isinstance(info, dict) and isinstance(m := info.get("mimetype"), str) and m:
            return m
        m = getattr(event, "mimetype", None)
        return m if isinstance(m, str) and m else None

    def _event_filename(self, event: MatrixMediaEvent, attachment_type: str) -> str:
        """Get filename from media event."""
        body = getattr(event, "body", None)
        if isinstance(body, str) and body.strip():
            if candidate := safe_filename(Path(body).name):
                return candidate
        return _DEFAULT_ATTACH_NAME if attachment_type == "file" else attachment_type

    def _build_attachment_path(
        self,
        event: MatrixMediaEvent,
        attachment_type: str,
        filename: str,
        mime: str | None,
    ) -> Path:
        """Build filesystem path for downloaded attachment."""
        safe_name = safe_filename(Path(filename).name) or _DEFAULT_ATTACH_NAME
        suffix = Path(safe_name).suffix
        if not suffix and mime:
            if guessed := mimetypes.guess_extension(mime, strict=False):
                safe_name, suffix = f"{safe_name}{guessed}", guessed
        stem = (Path(safe_name).stem or attachment_type)[:72]
        suffix = suffix[:16]
        event_id = safe_filename(str(getattr(event, "event_id", "") or "evt").lstrip("$"))
        event_prefix = (event_id[:24] or "evt").strip("_")
        return self._media_dir() / f"{event_prefix}_{stem}{suffix}"

    async def _download_media_bytes(self, mxc_url: str) -> bytes | None:
        """Download media from Matrix server."""
        if not self.client:
            return None
        response = await self.client.download(mxc=mxc_url)
        if isinstance(response, DownloadError):
            logger.warning("download failed for %s: %s", mxc_url, response)
            return None
        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        if isinstance(response, MemoryDownloadResponse):
            return bytes(response.body)
        if isinstance(body, (str, Path)):
            path = Path(body)
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    return None
        return None

    def _decrypt_media_bytes(self, event: MatrixMediaEvent, ciphertext: bytes) -> bytes | None:
        """Decrypt encrypted media bytes."""
        key_obj = getattr(event, "key", None)
        hashes = getattr(event, "hashes", None)
        iv = getattr(event, "iv", None)
        key = key_obj.get("k") if isinstance(key_obj, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not all(isinstance(v, str) for v in (key, sha256, iv)):
            return None
        try:
            return decrypt_attachment(ciphertext, key, sha256, iv)
        except (EncryptionError, ValueError, TypeError):
            logger.warning("decrypt failed for event %s", getattr(event, "event_id", ""))
            return None

    async def _fetch_media_attachment(
        self, room: MatrixRoom, event: MatrixMediaEvent
    ) -> tuple[dict[str, Any] | None, str]:
        """Download, decrypt if needed, and persist a Matrix attachment.

        Returns tuple of (attachment dict, marker text).
        """
        atype = self._event_attachment_type(event)
        mime = self._event_mime(event)
        filename = self._event_filename(event, atype)
        mxc_url = getattr(event, "url", None)
        fail = _ATTACH_FAILED.format(filename)

        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return None, fail

        limit_bytes = await self._effective_media_limit_bytes()
        declared = self._event_declared_size_bytes(event)
        if declared is not None and declared > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        downloaded = await self._download_media_bytes(mxc_url)
        if downloaded is None:
            return None, fail

        encrypted = self._is_encrypted_media_event(event)
        data = downloaded
        if encrypted:
            if (data := self._decrypt_media_bytes(event, downloaded)) is None:
                return None, fail

        if len(data) > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        path = self._build_attachment_path(event, atype, filename, mime)
        try:
            path.write_bytes(data)
        except OSError:
            return None, fail

        attachment = {
            "type": atype,
            "mime": mime,
            "filename": filename,
            "event_id": str(getattr(event, "event_id", "") or ""),
            "encrypted": encrypted,
            "size_bytes": len(data),
            "path": str(path),
            "mxc_url": mxc_url,
        }
        return attachment, _ATTACH_MARKER.format(path)

    def _base_metadata(self, room: MatrixRoom, event: RoomMessage) -> dict[str, Any]:
        """Build common metadata for text and media handlers."""
        meta: dict[str, Any] = {"room": getattr(room, "display_name", room.room_id)}
        if isinstance(eid := getattr(event, "event_id", None), str) and eid:
            meta["event_id"] = eid
        if thread := self._thread_metadata(event):
            meta.update(thread)
        return meta

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """Handle incoming text message."""
        if (
            event.sender == self.config.user_id
            or self._is_pre_startup_event(event)
            or not self._should_process_message(room, event)
        ):
            return
        await self._start_typing_keepalive(room.room_id)
        try:
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content=event.body,
                metadata=self._base_metadata(room, event),
                is_dm=self._is_direct_room(room),
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise

    async def _on_media_message(self, room: MatrixRoom, event: MatrixMediaEvent) -> None:
        """Handle incoming media message."""
        if (
            event.sender == self.config.user_id
            or self._is_pre_startup_event(event)
            or not self._should_process_message(room, event)
        ):
            return
        attachment, marker = await self._fetch_media_attachment(room, event)
        parts: list[str] = []
        if isinstance(body := getattr(event, "body", None), str) and body.strip():
            parts.append(body.strip())

        if attachment and attachment.get("type") == "audio":
            transcription = await self.transcribe_audio(attachment["path"])
            if transcription:
                parts.append(f"[transcription: {transcription}]")
            else:
                parts.append(marker)
        elif marker:
            parts.append(marker)

        await self._start_typing_keepalive(room.room_id)
        try:
            meta = self._base_metadata(room, event)
            meta["attachments"] = []
            if attachment:
                meta["attachments"] = [attachment]
            await self._handle_message(
                sender_id=event.sender,
                chat_id=room.room_id,
                content="\n".join(parts),
                media=[attachment["path"]] if attachment else [],
                metadata=meta,
                is_dm=self._is_direct_room(room),
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise


__all__ = ["MatrixChannel", "MatrixConfig"]
