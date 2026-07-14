# IG-234 TUI Background Messages Stream Rendering

## Context

After resume, daemon events are flowing but users still report no visible background updates in TUI.

## Root Cause

Background consumer primarily renders `updates` payloads via `StreamDisplayPipeline`. However, many user-visible progress signals (especially model text/tool activity) arrive via `messages` chunks and were ignored in background mode.

## Goals

1. Keep existing `updates` rendering behavior.
2. Add lightweight rendering for `messages` chunks during background subscription.
3. Avoid showing internal/system-only chunks.

## Implementation Plan

1. In `_consume_daemon_events_background`, handle `messages` mode tuple payloads.
2. Extract assistant-visible text from AI message content.
3. Mount extracted text as `AppMessage` lines.

## Validation

1. Compile-check TUI app module.
2. Resume a running thread and verify visible background updates in TUI.
