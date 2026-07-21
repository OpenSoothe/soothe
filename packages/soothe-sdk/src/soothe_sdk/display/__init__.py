"""Display-layer SDK package.

This package hosts:

* ``transcript_types`` — ``MessageData`` / ``MessageType`` / ``ToolStatus``
  dataclasses shared between TUI rendering and the host-resident
  ``CardBinder``.
* ``card_binder`` — pure event → ``MessageData`` binding logic, callable
  from either the TUI or the host.
* ``card_ledger`` — pure-Python ``CardMutation`` + ``InMemoryCardLedger``
  primitives backing the per-loop ``cards.jsonl`` on disk and the
  ``card.*`` wire schema.
* Tool-display helpers (``text_extract``, ``message_processing``,
  ``tool_message_format``, ``tool_result``) that the binder depends on,
  kept here so the binder has no client-side dependencies.
"""

from __future__ import annotations

from soothe_sdk.display.card_binder import (
    collect_cognition_card_replay,
    conversation_rows_to_langchain_messages,
    convert_combined_to_data,
    convert_event_to_message_data,
    convert_loop_events_to_data,
    convert_messages_to_data,
    is_loop_internal_checkpoint_message,
    merge_history_sources,
    merge_step_progress,
    merge_visible_messages_with_cognition_cards,
    parse_loop_event_timestamp,
    sanitize_resume_display_cards,
)
from soothe_sdk.display.card_ledger import (
    CARD_SCHEMA_VERSION,
    CardMutation,
    CardOp,
    InMemoryCardLedger,
    build_header_mutation,
    card_from_wire_dict,
    card_to_wire_dict,
    cards_to_mutations,
    utc_now_iso,
)
from soothe_sdk.display.snapshot_collapser import (
    build_goal_snapshot,
    fold_display_cards,
    split_cards_by_user_segments,
)
from soothe_sdk.display.snapshot_types import (
    GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION,
    GoalDisplaySnapshot,
    snapshot_from_dataclass_dict,
)
from soothe_sdk.display.text_extract import (
    extract_ai_text_for_display,
    extract_text_from_ai_message,
    extract_user_text_for_display,
    normalize_stream_message,
)
from soothe_sdk.display.transcript_types import (
    UPDATABLE_FIELDS,
    MessageData,
    MessageType,
    ToolStatus,
)

__all__ = [
    # Types
    "MessageData",
    "MessageType",
    "ToolStatus",
    "UPDATABLE_FIELDS",
    # Text extract
    "extract_ai_text_for_display",
    "extract_text_from_ai_message",
    "extract_user_text_for_display",
    "normalize_stream_message",
    # Binder
    "collect_cognition_card_replay",
    "convert_combined_to_data",
    "convert_event_to_message_data",
    "convert_loop_events_to_data",
    "convert_messages_to_data",
    "conversation_rows_to_langchain_messages",
    "is_loop_internal_checkpoint_message",
    "merge_history_sources",
    "merge_step_progress",
    "merge_visible_messages_with_cognition_cards",
    "parse_loop_event_timestamp",
    "sanitize_resume_display_cards",
    # Ledger
    "CARD_SCHEMA_VERSION",
    "CardMutation",
    "CardOp",
    "InMemoryCardLedger",
    "build_header_mutation",
    "card_from_wire_dict",
    "card_to_wire_dict",
    "cards_to_mutations",
    "utc_now_iso",
    # Goal display snapshots
    "GOAL_DISPLAY_SNAPSHOT_SCHEMA_VERSION",
    "GoalDisplaySnapshot",
    "build_goal_snapshot",
    "fold_display_cards",
    "snapshot_from_dataclass_dict",
    "split_cards_by_user_segments",
]
