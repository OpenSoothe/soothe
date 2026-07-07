# IG-168 Shared Essential UX Events

## Goal

Extract essential UX event filtering into a shared module under `soothe.ux.shared` so TUI and CLI-adjacent code can reuse one canonical event-type contract.

## Scope

- Add a new shared module for essential progress-event filtering.
- Replace TUI-local essential progress-event constants with shared imports.
- Keep existing rendering behavior unchanged; only centralize filtering rules.

## Design

Create `src/soothe/ux/shared/essential_events.py` with:

- `ESSENTIAL_PROGRESS_EVENT_TYPES`: canonical immutable set of event types for core progress display.
- `is_essential_progress_event_type(event_type: str) -> bool`: typed helper for filtering.

TUI adapter uses this helper before pipeline formatting.

## Acceptance Criteria

- No duplicated essential progress-event type lists in TUI adapter.
- TUI keeps rendering goal, loop reason/next action, step start, and step completion events.
- Existing focused unit tests continue to pass.
