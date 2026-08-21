"""Tests for ``loop_input.intake_scope`` validation."""

from __future__ import annotations

import pytest

from soothe_daemon.protocol.intake_scope import validate_and_normalize_intake_scope


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("minimal", "minimal"),
        (" SIMPLE ", "simple"),
        ("Complex", "complex"),
    ],
)
def test_validate_intake_scope_ok(raw: object | None, expected: str | None) -> None:
    scope, err = validate_and_normalize_intake_scope(raw, intent_hint=None)
    assert err is None
    assert scope == expected


@pytest.mark.parametrize(
    "raw",
    ["quiz", "chitchat", "moderate", 1],
)
def test_validate_intake_scope_rejects_invalid(raw: object) -> None:
    scope, err = validate_and_normalize_intake_scope(raw, intent_hint=None)
    assert scope is None
    assert err is not None
    assert "intake_scope" in err


def test_validate_intake_scope_rejects_daemon_intent_hint() -> None:
    scope, err = validate_and_normalize_intake_scope(
        "simple",
        intent_hint="text_completion",
    )
    assert scope is None
    assert err is not None
    assert "intent_hint" in err
