"""Tests for loop_input content normalization (IG-361)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from soothe.config import SootheConfig

from soothe_daemon.protocol import ErrorCode, MessageRouter
from soothe_daemon.protocol.router import (
    _coerce_loop_input_text,
    _queue_options_from_daemon_message,
)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("hello", "hello"),
        ("  hi  ", "hi"),
        ("", None),
        ("   ", None),
        ({"text": "Hello from loop input test"}, "Hello from loop input test"),
        ({"prompt": "p"}, "p"),
        ({"message": "m"}, "m"),
        ({"input": "i"}, "i"),
        ({"text": "  x  "}, "x"),
        ({}, None),
        ({"text": ""}, None),
        ({"other": "nope"}, None),
        (123, None),
        (None, None),
    ],
)
def test_coerce_loop_input_text(content: object, expected: str | None) -> None:
    assert _coerce_loop_input_text(content) == expected


def test_queue_options_from_daemon_message_defaults() -> None:
    assert _queue_options_from_daemon_message({}) == {
        "autonomous": False,
        "max_iterations": None,
        "preferred_subagent": None,
        "model": None,
        "model_params": None,
        "intent_hint": None,
        "response_schema": None,
        "response_schema_name": None,
        "response_schema_strict": None,
        "clarification_mode": None,
        "clarification_answer": False,
        "clarification_answers": None,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("auto", "auto"),
        ("AUTO", "auto"),
        ("  Manual  ", "manual"),
        ("manual", "manual"),
        ("", None),
        ("   ", None),
        ("turbo", None),
        (None, None),
        (42, None),
    ],
)
def test_queue_options_clarification_mode_normalized(value: object, expected: str | None) -> None:
    msg = {} if value is None else {"clarification_mode": value}
    assert _queue_options_from_daemon_message(msg)["clarification_mode"] == expected


def test_queue_options_from_daemon_message_response_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"word": {"type": "string"}},
        "required": ["word"],
    }
    out = _queue_options_from_daemon_message(
        {
            "response_schema": schema,
            "response_schema_name": " WordReply ",
            "response_schema_strict": False,
        }
    )
    assert out["response_schema"] == schema
    assert out["response_schema_name"] == "WordReply"
    assert out["response_schema_strict"] is False


@pytest.mark.parametrize(
    ("msg", "expected_max", "expected_model"),
    [
        ({"max_iterations": 0}, None, None),
        ({"max_iterations": -1}, None, None),
        ({"max_iterations": 3}, 3, None),
        ({"max_iterations": "3"}, None, None),
        ({"model": "  gpt-4  "}, None, "gpt-4"),
        ({"model": ""}, None, None),
        ({"model": 1}, None, None),
    ],
)
def test_queue_options_from_daemon_message_max_and_model(
    msg: dict[str, object],
    expected_max: int | None,
    expected_model: str | None,
) -> None:
    out = _queue_options_from_daemon_message(msg)
    assert out["max_iterations"] == expected_max
    assert out["model"] == expected_model


def test_queue_options_from_daemon_message_intent_hint_lowercased() -> None:
    assert _queue_options_from_daemon_message({"intent_hint": "  New_Goal  "})["intent_hint"] == (
        "new_goal"
    )


def test_queue_options_from_daemon_message_model_params_dict_only() -> None:
    d = {"a": 1}
    assert _queue_options_from_daemon_message({"model_params": d})["model_params"] is d
    assert _queue_options_from_daemon_message({"model_params": []})["model_params"] is None
    assert _queue_options_from_daemon_message({"model_params": "x"})["model_params"] is None


def test_queue_options_from_daemon_message_preferred_subagent_strip() -> None:
    assert (
        _queue_options_from_daemon_message({"preferred_subagent": "  x  "})["preferred_subagent"]
        == "x"
    )
    assert (
        _queue_options_from_daemon_message({"preferred_subagent": "   "})["preferred_subagent"]
        is None
    )
    assert (
        _queue_options_from_daemon_message({"preferred_subagent": 1})["preferred_subagent"] is None
    )


@pytest.mark.asyncio
async def test_loop_input_image_to_text_without_attachments_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """intent_hint image_to_text without attachments must not enqueue."""

    async def _stub_ensure(_self: MessageRouter, _loop_id: str) -> bool:
        return True

    monkeypatch.setattr(MessageRouter, "_ensure_loop_exists", _stub_ensure)

    sent: list[tuple[Any, dict[str, Any]]] = []
    enqueue = AsyncMock()
    loop_id = "019e0000-0000-7000-8000-000000000001"

    class _FakeDaemon:
        _config = SootheConfig()
        _query_running = False
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="thr-router-img")
        _loop_input_dispatcher = SimpleNamespace(enqueue=enqueue)
        _session_manager = SimpleNamespace(
            get_session=AsyncMock(return_value=SimpleNamespace(subscriptions={loop_id}))
        )

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    await router.dispatch(
        "client-go-parity",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "text without image",
                "intent_hint": "image_to_text",
            },
        },
    )

    enqueue.assert_not_awaited()
    assert sent
    err = sent[-1][1]
    assert err["type"] == "error"
    assert err["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert "attachment" in err["error"]["message"].lower()


TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _router_with_enqueue_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MessageRouter, AsyncMock, list[tuple[Any, dict[str, Any]]], str]:
    async def _stub_ensure(_self: MessageRouter, _loop_id: str) -> bool:
        return True

    monkeypatch.setattr(MessageRouter, "_ensure_loop_exists", _stub_ensure)

    sent: list[tuple[Any, dict[str, Any]]] = []
    enqueue = AsyncMock()
    loop_id = "019e0000-0000-7000-8000-000000000002"

    class _FakeDaemon:
        _config = SootheConfig()
        _query_running = False
        _active_threads: set[Any] = set()
        _runner = SimpleNamespace(current_thread_id="thr-router-direct")
        _loop_input_dispatcher = SimpleNamespace(enqueue=enqueue)
        _session_manager = SimpleNamespace(
            get_session=AsyncMock(return_value=SimpleNamespace(subscriptions={loop_id}))
        )
        _persistence_manager = SimpleNamespace(increment_loop_message_count=AsyncMock())

        async def _send_client_message(self, client_id: Any, msg: dict[str, Any]) -> None:
            sent.append((client_id, msg))

    router = MessageRouter(_FakeDaemon())
    return router, enqueue, sent, loop_id


@pytest.mark.asyncio
async def test_loop_input_direct_llm_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removed intent_hint direct_llm must not enqueue."""
    router, enqueue, sent, loop_id = _router_with_enqueue_stub(monkeypatch)

    await router.dispatch(
        "client-go-parity",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "hello",
                "intent_hint": "direct_llm",
            },
        },
    )

    enqueue.assert_not_awaited()
    err = sent[-1][1]
    assert err["type"] == "error"
    assert err["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert "removed" in err["error"]["message"].lower()


@pytest.mark.asyncio
async def test_loop_input_image_to_text_attachments_only_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """image_to_text with attachments and empty content is valid."""
    router, enqueue, sent, loop_id = _router_with_enqueue_stub(monkeypatch)

    await router.dispatch(
        "client-go-parity",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "",
                "intent_hint": "image_to_text",
                "attachments": [{"mime_type": "image/png", "data": TINY_PNG_B64}],
            },
        },
    )

    enqueue.assert_awaited_once()
    payload = enqueue.await_args.args[1]
    assert payload["intent_hint"] == "image_to_text"
    assert payload["attachments"]
    assert sent[-1][1]["type"] == "response"


@pytest.mark.asyncio
async def test_loop_input_text_completion_without_content_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, enqueue, sent, loop_id = _router_with_enqueue_stub(monkeypatch)

    await router.dispatch(
        "client-go-parity",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "",
                "intent_hint": "text_completion",
            },
        },
    )

    enqueue.assert_not_awaited()
    err = sent[-1][1]
    assert err["type"] == "error"
    assert err["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert "content" in err["error"]["message"].lower()


@pytest.mark.asyncio
async def test_loop_input_image_to_text_keeps_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, enqueue, _, loop_id = _router_with_enqueue_stub(monkeypatch)

    await router.dispatch(
        "client-go-parity",
        {
            "proto": "1",
            "type": "request",
            "method": "loop_input",
            "params": {
                "loop_id": loop_id,
                "content": "describe",
                "intent_hint": "image_to_text",
                "attachments": [{"mime_type": "image/png", "data": TINY_PNG_B64}],
            },
        },
    )

    enqueue.assert_awaited_once()
    payload = enqueue.await_args.args[1]
    assert payload["intent_hint"] == "image_to_text"
