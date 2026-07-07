# IG-120: Shared PresentationEngine wiring (Phase 2)

Tracks RFC-502 follow-up: one `PresentationEngine` instance shared by `CliRenderer` (via `StreamDisplayPipeline`) and `EventProcessor`, with final-answer dedup and verbosity gates centralized on the engine.

## Scope

- `PresentationEngine`: `final_answer_locked`, `reset_turn` / `reset_session`, `tier_visible()` for `should_show` consolidation.
- `EventProcessor`: optional `presentation_engine`; sync with `CliRenderer`; gate main assistant stream when locked; `mark_final_answer_locked` on chitchat/final custom events; reset presentation on session/turn boundaries.
- `CliRenderer` / `StreamDisplayPipeline`: injectable `presentation_engine`, `_rebind_presentation` for processor override.
- `TuiRenderer` / `SootheApp`: one `PresentationEngine` per app, passed to `TuiRenderer` and `EventProcessor` (same pattern as headless daemon); tool results summarized via shared engine.

## Status

Completed — `./scripts/verify_finally.sh` passed.
