# IG-169 Unify History JSONL Only

## Goal

Remove legacy `input_history.jsonl` compatibility and standardize TUI history to `history.jsonl` only.

## Scope

- Remove fallback reading from `input_history.jsonl`.
- Keep TUI history read/write strictly on configured `history.jsonl`.
- Update tests to validate unified-only behavior.

## Acceptance Criteria

- No `input_history.jsonl` read compatibility path remains in TUI history logic.
- TUI history writes continue to append structured entries to `history.jsonl`.
- Verification suite passes after the change.
