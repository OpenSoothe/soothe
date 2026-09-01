"""Unit tests for sticky composer mode helpers."""

from __future__ import annotations

import pytest

from soothe_cli.commands.subagent_routing import parse_subagent_from_input
from soothe_cli.tui.composer_mode import (
    COMPOSER_MODE_ASK,
    COMPOSER_MODE_AUTO,
    COMPOSER_MODE_BYPASS,
    COMPOSER_MODE_MANUAL,
    COMPOSER_MODE_PLAN,
    ComposerWireFields,
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
        ("ask", COMPOSER_MODE_ASK),
        ("bypass", COMPOSER_MODE_BYPASS),
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
        ("auto", "bypass"),
        ("bypass", "manual"),
        ("manual", "plan"),
        ("plan", "ask"),
        ("ask", "auto"),
        ("garbage", "auto"),
    ],
)
def test_next_composer_mode(current: str, expected: str) -> None:
    assert next_composer_mode(current) == expected


@pytest.mark.parametrize(
    ("mode", "wire_clar", "sticky", "interaction"),
    [
        ("auto", "auto", None, None),
        ("manual", "manual", None, None),
        ("plan", "auto", None, "plan"),
        ("ask", "auto", None, "ask"),
        ("bypass", "auto", None, "bypass"),
        ("garbage", "auto", None, None),
    ],
)
def test_resolve_composer_wire_fields(
    mode: str, wire_clar: str, sticky: str | None, interaction: str | None
) -> None:
    assert resolve_composer_wire_fields(mode) == ComposerWireFields(
        clarification_mode=wire_clar,
        preferred_subagent=sticky,
        interaction_mode=interaction,
    )


def test_sticky_plan_applies_when_no_slash_route() -> None:
    """Plan mode no longer injects a subagent; interaction_mode=plan is used."""
    parsed, cleaned = parse_subagent_from_input("draft a migration plan")
    sticky = None  # plan mode no longer sets preferred_subagent
    subagent = parsed or sticky
    assert subagent is None
    assert cleaned == "draft a migration plan"


def test_explicit_slash_route_wins_over_sticky_plan() -> None:
    """``/deep_research`` still wins when composer mode is Plan."""
    parsed, cleaned = parse_subagent_from_input("/deep_research find sources")
    sticky = None  # plan mode no longer sets preferred_subagent
    subagent = parsed or sticky
    assert subagent == "deep_research"
    assert cleaned == "find sources"
