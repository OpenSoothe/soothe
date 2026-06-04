"""Verify the CLI re-export shim wires through to the SDK types unchanged.

The CLI module ``soothe_cli.runtime.state.transcript`` used to *define*
``MessageData``/``MessageType``/``ToolStatus``. RFC-413 moved the
definitions into ``soothe_sdk.display.transcript_types`` and left a
re-export shim behind. This test guards against the shim being broken
into a duplicate-class copy (which would break ``isinstance`` checks in
the TUI).
"""

from __future__ import annotations

from soothe_cli.runtime.state import transcript as cli_transcript

from soothe_sdk.display import transcript_types as sdk_transcript_types


def test_message_data_class_identity_preserved() -> None:
    assert cli_transcript.MessageData is sdk_transcript_types.MessageData, (
        "CLI shim must re-export the SAME class object, not a copy"
    )


def test_message_type_class_identity_preserved() -> None:
    assert cli_transcript.MessageType is sdk_transcript_types.MessageType


def test_tool_status_class_identity_preserved() -> None:
    assert cli_transcript.ToolStatus is sdk_transcript_types.ToolStatus


def test_updatable_fields_identity_preserved() -> None:
    assert cli_transcript.UPDATABLE_FIELDS is sdk_transcript_types.UPDATABLE_FIELDS
