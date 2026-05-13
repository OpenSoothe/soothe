"""Tests for loop_input content normalization (IG-361)."""

from __future__ import annotations

import pytest

from soothe_daemon.message_router import _coerce_loop_input_text, _queue_options_from_daemon_message


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
        "interactive": False,
        "model": None,
        "model_params": None,
        "intent_hint": None,
    }


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
