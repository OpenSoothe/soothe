"""Tests for curated subagent wire helpers."""

from soothe_sdk.core.subagent_wire import (
    is_allowlisted_subagent_event_type,
    is_curated_subagent_wire_event_type,
    is_emit_allowed_subagent_wire_event_type,
    register_subagent_wire_event_types,
)


def test_curated_structural_match_for_soothe_subagent_types() -> None:
    assert is_curated_subagent_wire_event_type("soothe.subagent.deep_research.started")
    assert is_curated_subagent_wire_event_type("soothe.subagent.deep_research.milestone")
    assert is_curated_subagent_wire_event_type("soothe.subagent.browser_use.started")
    assert not is_curated_subagent_wire_event_type("soothe.capability.browser.started")


def test_emit_requires_registration() -> None:
    unregistered = "soothe.subagent._test_emit_gate.started"
    assert not is_emit_allowed_subagent_wire_event_type(unregistered)
    assert not is_emit_allowed_subagent_wire_event_type("soothe.subagent.browser_use.started")

    register_subagent_wire_event_types(unregistered)
    assert is_emit_allowed_subagent_wire_event_type(unregistered)


def test_consumer_allowlist_includes_structural_curated_types() -> None:
    assert is_allowlisted_subagent_event_type("soothe.subagent.deep_research.completed")
    assert is_allowlisted_subagent_event_type("soothe.subagent.browser_use.started")


def test_sdk_exports_no_subagent_type_constants() -> None:
    import soothe_sdk.core.subagent_wire as wire

    assert not any(name.startswith("SUBAGENT_") for name in dir(wire))
