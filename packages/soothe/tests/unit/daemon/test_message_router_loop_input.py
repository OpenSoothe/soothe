"""Tests for loop_input content normalization (IG-361)."""

from __future__ import annotations

import pytest

from soothe.daemon.message_router import _coerce_loop_input_text


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
