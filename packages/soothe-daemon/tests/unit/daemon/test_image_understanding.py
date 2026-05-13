"""Unit tests for IG-327 image attachment validation and vision preflight."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe_daemon.image_understanding import (
    enrich_user_text_with_vision,
    normalize_mime_type,
    validate_and_normalize_image_attachments,
)

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_normalize_mime_type_jpg_alias() -> None:
    assert normalize_mime_type("image/jpg") == "image/jpeg"


def test_validate_attachments_empty() -> None:
    out, err = validate_and_normalize_image_attachments(None)
    assert out == [] and err is None


def test_validate_attachments_valid_png() -> None:
    out, err = validate_and_normalize_image_attachments(
        [{"mime_type": "image/png", "data": TINY_PNG_B64}]
    )
    assert err is None
    assert len(out) == 1
    assert out[0]["mime_type"] == "image/png"
    assert out[0]["data"] == TINY_PNG_B64


def test_validate_attachments_invalid_mime() -> None:
    out, err = validate_and_normalize_image_attachments(
        [{"mime_type": "image/svg+xml", "data": TINY_PNG_B64}]
    )
    assert out == []
    assert err is not None


def test_validate_attachments_bad_base64() -> None:
    out, err = validate_and_normalize_image_attachments(
        [{"mime_type": "image/png", "data": "not!!!base64"}]
    )
    assert out == []
    assert "base64" in (err or "").lower()


@pytest.mark.asyncio
async def test_enrich_user_text_with_vision_invokes_image_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="saw a red square"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await enrich_user_text_with_vision(
        cfg,
        "what is it?",
        [{"mime_type": "image/png", "data": TINY_PNG_B64}],
    )
    assert "what is it?" in out
    assert "saw a red square" in out
    assert "Vision summary" in out
    cfg.create_chat_model.assert_called_once_with("image")
    fake_model.ainvoke.assert_awaited_once()
