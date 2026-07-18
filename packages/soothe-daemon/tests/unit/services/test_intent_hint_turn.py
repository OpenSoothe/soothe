"""Unit tests for intent-hint turns."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe_daemon.services.intent_hint_turn import (
    run_embed_turn,
    run_image_to_text_turn,
    run_intent_hint_turn,
    run_ocr_turn,
    run_text_completion_turn,
)

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
ATTACHMENTS = [{"mime_type": "image/png", "data": TINY_PNG_B64}]


@pytest.mark.asyncio
async def test_run_text_completion_turn_invokes_default_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="hello"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_text_completion_turn(cfg, user_text="hi")
    assert out == "hello"
    cfg.create_chat_model.assert_called_once_with("default")
    fake_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_image_to_text_turn_invokes_image_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="red pixel"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_image_to_text_turn(
        cfg,
        user_text="what color?",
        attachments=ATTACHMENTS,
    )
    assert out == "red pixel"
    cfg.create_chat_model.assert_called_once_with("image")
    fake_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_ocr_turn_invokes_ocr_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="HELLO"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_ocr_turn(cfg, user_text="", attachments=ATTACHMENTS)
    assert out == "HELLO"
    cfg.create_chat_model.assert_called_once_with("ocr")


@pytest.mark.asyncio
async def test_run_embed_turn_returns_json_vector() -> None:
    cfg = MagicMock()
    embedder = MagicMock()
    embedder.aembed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    cfg.create_embedding_model = MagicMock(return_value=embedder)

    out = await run_embed_turn(cfg, user_text="hello")
    assert '"embedding"' in out
    assert '"dimensions": 3' in out


@pytest.mark.asyncio
async def test_run_text_completion_rejects_empty_text() -> None:
    cfg = MagicMock()
    with pytest.raises(ValueError, match="text_completion"):
        await run_text_completion_turn(cfg, user_text="   ")


@pytest.mark.asyncio
async def test_run_intent_hint_turn_dispatches_embed() -> None:
    cfg = MagicMock()
    embedder = MagicMock()
    embedder.aembed_query = AsyncMock(return_value=[1.0])
    cfg.create_embedding_model = MagicMock(return_value=embedder)

    out = await run_intent_hint_turn(cfg, intent_hint="embed", user_text="x")
    assert '"dimensions": 1' in out
