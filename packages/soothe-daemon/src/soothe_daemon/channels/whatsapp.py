"""WhatsApp channel implementation using Node.js bridge.

Migrated from nanoBot with adaptations for soothe-daemon Channel architecture (RFC-620).
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
from collections import OrderedDict
from contextlib import suppress
from logging import getLogger
from pathlib import Path
from typing import Any, Literal

from soothe_daemon.channels.base import Channel
from soothe_daemon.channels.message import ChannelMessage

logger = getLogger(__name__)

WEBSOCKETS_AVAILABLE = importlib.util.find_spec("websockets") is not None


class WhatsAppConfig:
    """WhatsApp channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""
    allow_from: list[str] = []
    group_policy: Literal["open", "mention"] = "open"

    def __init__(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


def _bridge_token_path() -> Path:
    return Path.home() / ".soothe" / "whatsapp-auth" / "bridge-token"


def _load_or_create_bridge_token(path: Path) -> str:
    """Load a persisted bridge token or create one on first use."""
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    with suppress(OSError):
        path.chmod(0o600)
    return token


def _ensure_bridge_setup() -> Path:
    """Ensure the WhatsApp bridge is set up and built.

    Returns the bridge directory. Raises RuntimeError if npm is not found.
    """
    # Look for bridge source in nanobot package
    user_bridge = Path.home() / ".soothe" / "whatsapp-bridge"
    stamp_file = user_bridge / ".soothe-bridge-source-hash"

    # Find source bridge
    current_file = Path(__file__)
    pkg_bridge = current_file.parent.parent.parent / "bridge"
    src_bridge = current_file.parent.parent.parent.parent.parent / "nanoBot" / "bridge"

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        raise RuntimeError(
            "WhatsApp bridge source not found. The bridge must be installed separately."
        )

    def source_hash(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if rel.parts and rel.parts[0] in {"node_modules", "dist"}:
                continue
            digest.update(rel.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    expected_hash = source_hash(source)
    current_hash = stamp_file.read_text().strip() if stamp_file.exists() else None

    if (user_bridge / "dist" / "index.js").exists() and current_hash == expected_hash:
        return user_bridge

    if (user_bridge / "dist" / "index.js").exists() and current_hash != expected_hash:
        logger.info("[WhatsApp] Bridge source changed; rebuilding bridge...")

    npm_path = shutil.which("npm")
    if not npm_path:
        raise RuntimeError("npm not found. Please install Node.js >= 18.")

    logger.info("[WhatsApp] Setting up bridge...")
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    logger.info("[WhatsApp] Installing dependencies...")
    subprocess.run([npm_path, "install"], cwd=user_bridge, check=True, capture_output=True)

    logger.info("[WhatsApp] Building...")
    subprocess.run([npm_path, "run", "build"], cwd=user_bridge, check=True, capture_output=True)
    stamp_file.write_text(expected_hash + "\n")

    logger.info("[WhatsApp] Bridge ready")
    return user_bridge


class WhatsAppChannel(Channel):
    """WhatsApp channel that connects to a Node.js bridge.

    The bridge uses @whiskeysockets/baileys to handle the WhatsApp Web protocol.
    Communication between Python and Node.js is via WebSocket.
    """

    name = "whatsapp"
    display_name = "WhatsApp"
    supports_inbound = True
    supports_outbound = True
    supports_streaming = False

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return WhatsAppConfig().__dict__

    def __init__(self, config: Any, manager: Any) -> None:
        super().__init__(config, manager)
        if isinstance(config, dict):
            self.config = WhatsAppConfig(**config)
        else:
            self.config = config
        self._ws: Any = None
        self._connected = False
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._lid_to_phone: dict[str, str] = {}
        self._bridge_token: str | None = None

    def _effective_bridge_token(self) -> str:
        """Resolve the bridge token, generating a local secret when needed."""
        if self._bridge_token is not None:
            return self._bridge_token
        configured = self.config.bridge_token.strip()
        if configured:
            self._bridge_token = configured
        else:
            self._bridge_token = _load_or_create_bridge_token(_bridge_token_path())
        return self._bridge_token

    async def login(self, force: bool = False) -> bool:
        """Set up and run the WhatsApp bridge for QR code login.

        This spawns the Node.js bridge process which handles the WhatsApp
        authentication flow.
        """
        if not WEBSOCKETS_AVAILABLE:
            logger.error("[WhatsApp] websockets not installed")
            return False

        try:
            bridge_dir = _ensure_bridge_setup()
        except RuntimeError:
            logger.exception("[WhatsApp] Bridge setup failed")
            return False

        env = {**os.environ}
        env["BRIDGE_TOKEN"] = self._effective_bridge_token()
        env["AUTH_DIR"] = str(_bridge_token_path().parent)

        logger.info("[WhatsApp] Starting bridge for QR login...")
        try:
            subprocess.run(
                [shutil.which("npm"), "start"],
                cwd=bridge_dir,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError:
            return False

        return True

    async def start(self) -> None:
        """Start the WhatsApp channel by connecting to the bridge."""
        if not WEBSOCKETS_AVAILABLE:
            logger.error("[WhatsApp] websockets not installed")
            return

        import websockets

        bridge_url = self.config.bridge_url

        logger.info("[WhatsApp] Connecting to bridge at %s...", bridge_url)

        self._running = True

        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    await ws.send(
                        json.dumps({"type": "auth", "token": self._effective_bridge_token()})
                    )
                    self._connected = True
                    logger.info("[WhatsApp] Connected to bridge")

                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception:
                            logger.exception("[WhatsApp] Error handling bridge message")

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("[WhatsApp] Bridge connection error: %s", e)

                if self._running:
                    logger.info("[WhatsApp] Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the WhatsApp channel."""
        self._running = False
        self._connected = False

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, chat_id: str, message: ChannelMessage) -> None:
        """Send a message through WhatsApp."""
        if not self._ws or not self._connected:
            logger.warning("[WhatsApp] Bridge not connected")
            return

        if message.content:
            try:
                payload = {"type": "send", "to": chat_id, "text": message.content}
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                logger.exception("[WhatsApp] Error sending message")
                raise

        for media_path in message.media or []:
            try:
                mime, _ = mimetypes.guess_type(media_path)
                payload = {
                    "type": "send_media",
                    "to": chat_id,
                    "filePath": media_path,
                    "mimetype": mime or "application/octet-stream",
                    "fileName": media_path.rsplit("/", 1)[-1],
                }
                await self._ws.send(json.dumps(payload, ensure_ascii=False))
            except Exception:
                logger.exception("[WhatsApp] Error sending media %s", media_path)
                raise

    async def _handle_bridge_message(self, raw: str) -> None:
        """Handle a message from the bridge."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[WhatsApp] Invalid JSON from bridge: %s", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "message":
            pn = data.get("pn", "")
            sender = data.get("sender", "")
            content = data.get("content", "")
            message_id = data.get("id", "")

            is_group = data.get("isGroup", False)
            was_mentioned = data.get("wasMentioned", False)

            if is_group and self.config.group_policy == "mention":
                if not was_mentioned:
                    return

            raw_a = pn or ""
            raw_b = sender or ""
            id_a = raw_a.split("@")[0] if "@" in raw_a else raw_a
            id_b = raw_b.split("@")[0] if "@" in raw_b else raw_b

            phone_id = ""
            lid_id = ""
            for raw, extracted in [(raw_a, id_a), (raw_b, id_b)]:
                if "@s.whatsapp.net" in raw:
                    phone_id = extracted
                elif "@lid.whatsapp.net" in raw:
                    lid_id = extracted
                elif extracted and not phone_id:
                    phone_id = extracted

            sender_id = phone_id or self._lid_to_phone.get(lid_id, "") or lid_id or id_a or id_b
            if not self.is_allowed(sender_id):
                return

            if message_id:
                if message_id in self._processed_message_ids:
                    return
                self._processed_message_ids[message_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)

            if phone_id and lid_id:
                self._lid_to_phone[lid_id] = phone_id

            logger.info(
                "[WhatsApp] Sender phone=%s lid=%s → sender_id=%s",
                phone_id or "(empty)",
                lid_id or "(empty)",
                sender_id,
            )

            media_paths = data.get("media") or []

            if content == "[Voice Message]":
                if media_paths:
                    logger.info("[WhatsApp] Transcribing voice message from %s...", sender_id)
                    transcription = await self.transcribe_audio(media_paths[0])
                    if transcription:
                        content = transcription
                        media_paths = []
                        logger.info(
                            "[WhatsApp] Transcribed voice from %s: %s...",
                            sender_id,
                            transcription[:50],
                        )
                    else:
                        content = "[Voice Message: Transcription failed]"
                else:
                    content = "[Voice Message: Audio not available]"

            if media_paths:
                for p in media_paths:
                    mime, _ = mimetypes.guess_type(p)
                    media_type = "image" if mime and mime.startswith("image/") else "file"
                    media_tag = f"[{media_type}: {p}]"
                    content = f"{content}\n{media_tag}" if content else media_tag

            await self._handle_message(
                sender_id=sender_id,
                chat_id=sender,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False),
                },
            )

        elif msg_type == "status":
            status = data.get("status")
            logger.info("[WhatsApp] Status: %s", status)

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            logger.info("[WhatsApp] Scan QR code in the bridge terminal to connect")

        elif msg_type == "error":
            logger.error("[WhatsApp] Bridge error: %s", data.get("error"))
