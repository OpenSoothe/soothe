"""Unit tests for unified direct_llm / vision direct turns."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from soothe_daemon.services.direct_llm_turn import run_direct_llm_turn, run_image_to_text_turn

TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
ATTACHMENTS = [{"mime_type": "image/png", "data": TINY_PNG_B64}]


@pytest.mark.asyncio
async def test_run_direct_llm_turn_text_only_invokes_default_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="hello"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_direct_llm_turn(cfg, user_text="hi")
    assert out == "hello"
    cfg.create_chat_model.assert_called_once_with("default")
    fake_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_direct_llm_turn_with_attachments_invokes_image_model() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="red pixel"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_direct_llm_turn(
        cfg,
        user_text="what color?",
        attachments=ATTACHMENTS,
    )
    assert out == "red pixel"
    cfg.create_chat_model.assert_called_once_with("image")
    fake_model.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_direct_llm_turn_rejects_empty_text_without_attachments() -> None:
    cfg = MagicMock()
    with pytest.raises(ValueError, match="user_text or attachments"):
        await run_direct_llm_turn(cfg, user_text="   ")


@pytest.mark.asyncio
async def test_run_direct_llm_turn_rejects_response_schema_with_attachments() -> None:
    cfg = MagicMock()
    with pytest.raises(ValueError, match="response_schema"):
        await run_direct_llm_turn(
            cfg,
            user_text="describe",
            attachments=ATTACHMENTS,
            response_schema={"type": "object"},
        )


@pytest.mark.asyncio
async def test_run_image_to_text_turn_delegates_to_direct_llm() -> None:
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=AIMessage(content="legacy path"))

    cfg = MagicMock()
    cfg.create_chat_model = MagicMock(return_value=fake_model)

    out = await run_image_to_text_turn(
        cfg,
        user_text="",
        attachments=ATTACHMENTS,
    )
    assert out == "legacy path"
    cfg.create_chat_model.assert_called_once_with("image")
