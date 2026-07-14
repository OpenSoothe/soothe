# IG-468: CardBinder Extraction (RFC-413 Phase 2)

**Guide**: IG-468
**Title**: Extract Card Binding Logic into `soothe_sdk.display.card_binder`
**Created**: 2026-06-04
**Related RFCs**: RFC-413 (Server-Owned Display Card Ledger)
**Scope**: Pure refactor — zero observable behavior change. Sets up the binder module so Phase 3 can move it to the daemon.

---

## Goal

Move all event → card binding logic out of `_history.py` (and adjacent helpers) into a new `soothe_sdk.display.card_binder` module that:

* Has **no Textual / widget / rendering dependencies** — only stdlib + langchain message types.
* Is **runnable from either the CLI today or the daemon in Phase 3** without code changes.
* Is **unit-testable against canned event traces** without instantiating `SootheApp`.
* Preserves the existing `MessageData` return type so the CLI's downstream rendering pipeline is unchanged.

"Pure refactor" means: every existing TUI test continues to pass with the binder calls re-pointed at the new module. No new card kinds, no new wire frames, no new persistence — those land in Phase 3.

## Background

Today the binding logic is spread across `_HistoryMixin` (`packages/soothe-cli/src/soothe_cli/tui/app/_history.py`, ~970 lines) as a mix of static methods and instance methods. The instance methods that do I/O (`_get_loop_state_values`, `_fetch_loop_activity_events`, `_fetch_loop_history_data`) call the daemon — those **stay** in the TUI. Only the pure transformation functions move.

`MessageData`, `MessageType`, and `ToolStatus` (defined in `packages/soothe-cli/src/soothe_cli/runtime/state/transcript.py`) are pure dataclasses with no Textual dependency. They move to the SDK so the binder can return them without importing CLI code.

## What Moves

### Pure-binding functions → `soothe_sdk.display.card_binder`

From `packages/soothe-cli/src/soothe_cli/tui/app/_history.py`:

| Existing symbol | New location |
|---|---|
| `_HistoryMixin._is_loop_internal_checkpoint_message` | `card_binder.is_loop_internal_checkpoint_message` |
| `_HistoryMixin._merge_visible_messages_with_cognition_cards` | `card_binder.merge_visible_messages_with_cognition_cards` |
| `_HistoryMixin._convert_messages_to_data` | `card_binder.convert_messages_to_data` |
| `_HistoryMixin._conversation_rows_to_langchain_messages` | `card_binder.conversation_rows_to_langchain_messages` |
| `_HistoryMixin._parse_loop_event_timestamp` | `card_binder.parse_loop_event_timestamp` |
| `_HistoryMixin._convert_event_to_message_data` | `card_binder.convert_event_to_message_data` |
| `_HistoryMixin._collect_cognition_card_replay` | `card_binder.collect_cognition_card_replay` |
| `_HistoryMixin._merge_step_progress` | `card_binder.merge_step_progress` |
| `_HistoryMixin._convert_loop_events_to_data` | `card_binder.convert_loop_events_to_data` |
| `_HistoryMixin._merge_history_sources` | `card_binder.merge_history_sources` |
| `_HistoryMixin._convert_combined_to_data` | `card_binder.convert_combined_to_data` |

All move as module-level functions. `_HistoryMixin` instance methods that don't touch `self` become trivial pass-throughs that delegate to the SDK module (kept for one release for API stability, then removed in Phase 3).

### Data types → `soothe_sdk.display.transcript_types`

From `packages/soothe-cli/src/soothe_cli/runtime/state/transcript.py`:

| Symbol | New location |
|---|---|
| `MessageType` (StrEnum) | `soothe_sdk.display.transcript_types.MessageType` |
| `ToolStatus` (StrEnum) | `soothe_sdk.display.transcript_types.ToolStatus` |
| `MessageData` (dataclass) | `soothe_sdk.display.transcript_types.MessageData` |
| `UPDATABLE_FIELDS` (frozenset) | `soothe_sdk.display.transcript_types.UPDATABLE_FIELDS` |

The existing `soothe_cli/runtime/state/transcript.py` becomes a **re-export shim**:

```python
"""Transcript message models for TUI display.

These types now live in ``soothe_sdk.display.transcript_types`` so they can be
shared with the daemon-resident CardBinder (RFC-413). This module re-exports
them to preserve the CLI's existing import paths.
"""
from __future__ import annotations

from soothe_sdk.display.transcript_types import (  # noqa: F401
    UPDATABLE_FIELDS,
    MessageData,
    MessageType,
    ToolStatus,
)

__all__ = ["UPDATABLE_FIELDS", "MessageData", "MessageType", "ToolStatus"]
```

No other CLI files change their imports.

### Stays in place

* `MessageStore` (the DOM-window collection in `widgets/message_store.py`) — Textual-aware.
* `_HistoryMixin` instance methods that hit the daemon (`_get_loop_state_values`, `_fetch_loop_activity_events`, `_fetch_loop_history_data`, `_recover_missing_checkpoint_messages`, `_consume_daemon_events_background`).
* All TUI widgets, the renderer, the message-store mixin, the executor mixin.

## New File Structure

```
packages/soothe-sdk/src/soothe_sdk/display/
  ├─ __init__.py             ← exports: CardBinder, MessageData, MessageType, ToolStatus, ...
  ├─ card_binder.py          ← extracted pure-binding functions (Phase 2)
  └─ transcript_types.py     ← MessageData, MessageType, ToolStatus, UPDATABLE_FIELDS
```

`__init__.py` re-exports the public surface so consumers can write `from soothe_sdk.display import convert_messages_to_data, MessageData`.

## Implementation Plan

### Step 1 — Move data types (low risk, mechanical)

1. Copy contents of `soothe_cli/runtime/state/transcript.py` (minus logger setup) to `soothe_sdk/display/transcript_types.py`.
2. Replace original file with the re-export shim shown above.
3. Run `pytest packages/soothe-cli/tests/` — all should pass unchanged (import paths preserved by the shim).

### Step 2 — Create `card_binder.py` with extracted functions

1. Create `soothe_sdk/display/card_binder.py`.
2. Move each function from the table above. Convert `@staticmethod` decorators away (module-level functions), drop the `self`/`cls` parameters, fix internal references (`_HistoryMixin._x(...)` → direct call).
3. Add per-function docstrings describing inputs/outputs (currently many are terse).
4. **Imports allowed**: stdlib, `langchain_core.messages`, `soothe_sdk.display.transcript_types`, `soothe_sdk.langchain_wire` (for `messages_from_wire_dicts` if needed). No Textual, no CLI imports.

### Step 3 — Update `_history.py` to delegate

Replace each moved function body with a one-line delegate:

```python
@staticmethod
def _convert_messages_to_data(
    messages: list[Any],
    *,
    cognition_card_replay: list[MessageData] | None = None,
) -> list[MessageData]:
    """Delegates to soothe_sdk.display.card_binder.convert_messages_to_data."""
    from soothe_sdk.display.card_binder import convert_messages_to_data
    return convert_messages_to_data(messages, cognition_card_replay=cognition_card_replay)
```

This preserves the existing `SootheApp._convert_messages_to_data(...)` API used by tests in `test_convert_messages_to_data.py`.

### Step 4 — Add SDK-level unit tests

Mirror `packages/soothe-cli/tests/unit/tui/test_convert_messages_to_data.py` in a new SDK test file `packages/soothe-sdk/tests/unit/display/test_card_binder.py` that calls the SDK functions directly (no `SootheApp` construction). The CLI tests stay — they now exercise the delegation path.

### Step 5 — Verify

Run `./scripts/verify_finally.sh`. Every test must pass. Manual TUI smoke: start a new loop, run a couple of turns, resume it, confirm transcript renders identically to before.

## Test Plan

| Test | What it proves |
|---|---|
| Existing `tests/unit/tui/test_convert_messages_to_data.py` (5+ tests) passes unchanged | TUI consumer API and behavior preserved |
| Existing `tests/unit/tui/test_step_card_*.py` passes unchanged | Step / tool binding still correct |
| New `tests/unit/display/test_card_binder.py` (mirror of TUI tests + a few SDK-level traces) | Binder works when called as a pure module |
| New `tests/unit/display/test_transcript_types_reexport.py` (1-line `assert MessageData is sdk.MessageData`) | Shim is a true re-export, not a copy |
| `./scripts/verify_finally.sh` green | Formatting, lint, all unit tests |

Manual smoke is required because mock-heavy unit tests can mask widget regressions:

1. Start a fresh loop, run 3–5 turns with tool calls + cognition cards, confirm transcript looks normal.
2. Restart TUI with `soothe loop continue <id>`, confirm historical transcript identical to pre-refactor.
3. Use `/loops` to switch into another loop, confirm IG-467 behavior still works.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| **Hidden coupling**: a "pure-binding" function imports something Textual-specific transitively | Run `python -c "from soothe_sdk.display.card_binder import *"` from a fresh venv with only SDK deps. CI smoke for SDK isolation. |
| **Pickle / dataclass identity**: moving `MessageData` changes its `__module__`, breaking anything that pickled or checked `type(...) is MessageData` | The shim re-imports the same class object, preserving identity. Test added in Step 5. |
| **Tests in `test_convert_messages_to_data.py` use `SootheApp._convert_messages_to_data(...)` as a method** | Keep `_HistoryMixin` delegation methods (Step 3); tests continue to work. |
| **Circular imports** if `soothe_sdk` ever needs CLI types | Forbidden by design — `soothe_sdk` is the lower layer. CI rule already enforces. |
| **Logger naming churn**: extracted functions log under the SDK module name now | Acceptable. Existing log lines in `_history.py` had no consumers asserting their module path. |

## Out of Scope (Phase 3 deferrals)

* New `CardMutation` typed schema (current binder returns `list[MessageData]`; Phase 3 introduces the diff-stream model).
* `DisplayCardLedger` and `cards.jsonl` persistence.
* `card.*` wire frames.
* Removing `_STALE_TURN_PENDING_TYPES` filtering.
* Daemon execution of `CardBinder`.

## Done When

* `soothe_sdk/display/card_binder.py` and `transcript_types.py` exist with the extracted functions/types.
* `_history.py` is reduced to I/O methods + thin delegation wrappers.
* CLI re-export shim in `runtime/state/transcript.py` preserves all current import paths.
* All existing tests pass unchanged.
* New SDK-level binder tests pass.
* Manual TUI smoke confirms no visible regression.
* PR description documents the refactor and explicitly notes "no behavior change."
