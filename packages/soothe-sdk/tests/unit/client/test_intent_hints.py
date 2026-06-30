"""Client-side ``loop_input.intent_hint`` validation."""

from __future__ import annotations

import pytest

from soothe_sdk.client.intent_hints import (
    EMBED,
    IMAGE_TO_TEXT,
    OCR,
    TEXT_COMPLETION,
    validate_loop_input_intent_hint,
)
from soothe_sdk.client.websocket import WebSocketClient


class _CapturingClient(WebSocketClient):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict] = []

    async def send(self, message: dict) -> None:  # type: ignore[override]
        self.sent.append(message)


def test_validate_loop_input_intent_hint_rejects_legacy() -> None:
    for hint in ("direct_llm", "DIRECT_LLM", " quiz ", "quiz"):
        err = validate_loop_input_intent_hint(hint)
        assert err is not None
        assert "removed" in err


def test_validate_loop_input_intent_hint_allows_direct_and_pass_through() -> None:
    for hint in (
        TEXT_COMPLETION,
        IMAGE_TO_TEXT,
        OCR,
        EMBED,
        "resume_clarification",
        "skill:search",
    ):
        assert validate_loop_input_intent_hint(hint) is None


@pytest.mark.asyncio
async def test_send_input_rejects_legacy_intent_hint() -> None:
    client = _CapturingClient()
    with pytest.raises(ValueError, match="direct_llm is removed"):
        await client.send_input("loop-1", "hello", intent_hint="direct_llm")
    assert client.sent == []


@pytest.mark.asyncio
async def test_send_input_passes_resume_clarification() -> None:
    client = _CapturingClient()
    await client.send_input(
        "loop-1",
        "answer",
        intent_hint="resume_clarification",
        clarification_answer=True,
    )
    params = client.sent[-1]["params"]
    assert params["intent_hint"] == "resume_clarification"
    assert params["clarification_answer"] is True
