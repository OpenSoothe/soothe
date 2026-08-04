"""Unit tests for sticky composer mode helpers (IG-682)."""

from __future__ import annotations

import pytest

from soothe_cli.tui.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.tui.composer_mode import (
    COMPOSER_MODE_AUTO,
    COMPOSER_MODE_MANUAL,
    COMPOSER_MODE_PLAN,
    next_composer_mode,
    normalize_composer_mode,
    resolve_composer_wire_fields,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("auto", COMPOSER_MODE_AUTO),
        ("manual", COMPOSER_MODE_MANUAL),
        ("plan", COMPOSER_MODE_PLAN),
        (None, COMPOSER_MODE_AUTO),
        ("garbage", COMPOSER_MODE_AUTO),
        ("", COMPOSER_MODE_AUTO),
    ],
)
def test_normalize_composer_mode(raw: str | None, expected: str) -> None:
    assert normalize_composer_mode(raw) == expected


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        ("auto", "manual"),
        ("manual", "plan"),
        ("plan", "auto"),
        ("garbage", "auto"),
    ],
)
def test_next_composer_mode(current: str, expected: str) -> None:
    assert next_composer_mode(current) == expected


@pytest.mark.parametrize(
    ("mode", "wire_clar", "sticky"),
    [
        ("auto", "auto", None),
        ("manual", "manual", None),
        ("plan", "auto", "planner"),
        ("garbage", "auto", None),
    ],
)
def test_resolve_composer_wire_fields(mode: str, wire_clar: str, sticky: str | None) -> None:
    assert resolve_composer_wire_fields(mode) == (wire_clar, sticky)


def test_sticky_plan_applies_when_no_slash_route() -> None:
    """Plan mode injects planner when the message has no subagent slash."""
    parsed, cleaned = parse_subagent_from_input("draft a migration plan")
    sticky = "planner"
    subagent = parsed or sticky
    assert subagent == "planner"
    assert cleaned == "draft a migration plan"


def test_explicit_slash_route_wins_over_sticky_plan() -> None:
    """``/deep_research`` still wins when composer mode is Plan."""
    parsed, cleaned = parse_subagent_from_input("/deep_research find sources")
    sticky = "planner"
    subagent = parsed or sticky
    assert subagent == "deep_research"
    assert cleaned == "find sources"
