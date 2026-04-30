"""Vision preflight for daemon input with image attachments (IG-327)."""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# Align with TUI media limits (packages/soothe-cli/.../media_utils.py)
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_IMAGES_PER_MESSAGE = 8

_ALLOWED_MIME: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "image/bmp",
    }
)
_MIME_ALIASES: dict[str, str] = {
    "image/jpg": "image/jpeg",
    "image/pjpeg": "image/jpeg",
}


def normalize_mime_type(mime: str) -> str | None:
    """Return canonical image MIME or None if unsupported."""
    cleaned = mime.strip().lower()
    if cleaned in _MIME_ALIASES:
        cleaned = _MIME_ALIASES[cleaned]
    return cleaned if cleaned in _ALLOWED_MIME else None


def validate_and_normalize_image_attachments(raw: Any) -> tuple[list[dict[str, str]], str | None]:
    """Validate wire ``attachments`` and return normalized dicts for the queue.

    Args:
        raw: ``msg["attachments"]`` from client (may be missing / invalid).

    Returns:
        Tuple of (normalized list of ``{"mime_type", "data"}``, error message).
        On success the error message is ``None``.
    """
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return [], "attachments must be a JSON array"
    if len(raw) > _MAX_IMAGES_PER_MESSAGE:
        return [], f"at most {_MAX_IMAGES_PER_MESSAGE} image attachments allowed"

    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return [], f"attachment[{i}] must be an object"
        mime_raw = item.get("mime_type")
        data_raw = item.get("data")
        if not isinstance(mime_raw, str) or not mime_raw.strip():
            return [], f"attachment[{i}].mime_type must be a non-empty string"
        if not isinstance(data_raw, str) or not data_raw.strip():
            return [], f"attachment[{i}].data must be a non-empty base64 string"

        mime = normalize_mime_type(mime_raw)
        if mime is None:
            return [], f"attachment[{i}].mime_type is not an allowed image type"

        try:
            decoded = base64.b64decode(data_raw, validate=True)
        except binascii.Error:
            return [], f"attachment[{i}].data is not valid base64"

        if len(decoded) > _MAX_IMAGE_BYTES:
            return [], f"attachment[{i}] exceeds maximum decoded size ({_MAX_IMAGE_BYTES} bytes)"

        out.append({"mime_type": mime, "data": data_raw.strip()})

    return out, None


_VISION_INSTRUCTION = (
    "Describe the attached image(s) concisely for another assistant that will "
    "handle the user's request. Focus on visible objects, text, charts, and intent."
)


async def enrich_user_text_with_vision(
    config: Any,
    text: str,
    attachments: list[dict[str, str]],
) -> str:
    """Run the configured image-role model on images and merge output into user text.

    Args:
        config: ``SootheConfig`` with providers for role ``image``.
        text: User text (may be empty).
        attachments: Normalized list from ``validate_and_normalize_image_attachments``.

    Returns:
        Text passed to ``SootheRunner.astream`` (user text plus vision block).

    Raises:
        Exception: Propagated from the vision model if the call fails.
    """
    if not attachments:
        return text

    model = config.create_chat_model("image")
    blocks: list[str | dict[str, Any]] = [
        {"type": "text", "text": _VISION_INSTRUCTION},
    ]
    for att in attachments:
        mime = att["mime_type"]
        b64 = att["data"]
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    msg = HumanMessage(content=blocks)
    response = await model.ainvoke([msg])
    summary = str(response.content).strip()
    if not summary:
        summary = "(Vision model returned empty content.)"

    user_part = text.strip()
    vision_block = f"--- Vision summary ---\n{summary}\n---"
    if user_part:
        return f"{user_part}\n\n{vision_block}\n"
    return f"{vision_block}\n"
