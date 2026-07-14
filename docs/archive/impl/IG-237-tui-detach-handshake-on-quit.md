# IG-237 TUI Detach Handshake on Quit

## Context

`Ctrl+D` in the daemon-backed TUI currently exits immediately. In some runs this can race with websocket teardown, so the daemon observes a disconnect before a detach intent and may stop the active turn.

## Goal

Ensure quit-from-TUI performs a reliable detach handshake before app exit when a daemon session is active.

## Implementation Plan

1. Add a dedicated async helper that sends detach and only then exits the app.
2. Route both `Ctrl+D` quit flow and explicit detach action through the same helper.
3. Guard against duplicate detach calls while a detach is already in progress.

## Validation

1. Start a long-running turn, press `Ctrl+D`, and confirm daemon thread keeps running.
2. Run `soothe thread continue` and confirm the same thread can be reattached.
3. Confirm no regressions for normal quit when no daemon session is active.
