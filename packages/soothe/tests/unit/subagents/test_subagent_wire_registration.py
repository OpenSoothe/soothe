"""Subagent wire types are owned by soothe subagent modules, not soothe-sdk constants."""

import soothe_sdk.core.subagent_wire as wire
from soothe_sdk.core.subagent_wire import (
    get_allowlisted_subagent_event_types,
    is_emit_allowed_subagent_wire_event_type,
    register_subagent_wire_event_types,
)

from soothe.subagents.tacitus import events as tacitus_events


def test_tacitus_wire_types_registered_via_register_event() -> None:
    assert is_emit_allowed_subagent_wire_event_type(tacitus_events.SUBAGENT_TACITUS_STARTED)
    assert is_emit_allowed_subagent_wire_event_type(tacitus_events.SUBAGENT_TACITUS_GATHER_SUMMARY)
    assert is_emit_allowed_subagent_wire_event_type(tacitus_events.SUBAGENT_TACITUS_COMPLETED)


def test_importing_subagents_package_registers_builtin_wire_types() -> None:
    import soothe.subagents  # noqa: F401

    assert is_emit_allowed_subagent_wire_event_type(tacitus_events.SUBAGENT_TACITUS_STARTED)


def test_sdk_does_not_export_subagent_type_constants() -> None:
    assert not any(name.startswith("SUBAGENT_") for name in dir(wire))


def test_plugin_can_register_custom_wire_types() -> None:
    custom = "soothe.subagent.custom_plugin.started"
    register_subagent_wire_event_types(custom)
    assert is_emit_allowed_subagent_wire_event_type(custom)
    assert custom in get_allowlisted_subagent_event_types()
