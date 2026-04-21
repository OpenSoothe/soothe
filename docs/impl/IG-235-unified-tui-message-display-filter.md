# IG-235 Unified TUI Message Display Filter

## Context

TUI message display behavior diverged between:

- live background streaming (`_consume_daemon_events_background`)
- recovered history rendering (`_convert_messages_to_data`)

This caused core conversation messages (Human/AI) to be rendered inconsistently:
history showed proper user/assistant cards, while live background flow often fell back to plain app text rows.

## Root Cause

Message normalization and display filtering rules were duplicated across separate code paths with different heuristics.
The live path relied on ad-hoc text extraction, while the history path used typed message conversion rules.

## Plan

1. Add a shared TUI message-display filter utility for:
   - wire message normalization to LangChain message objects
   - user message filtering (including `[SYSTEM]` suppression)
   - assistant text extraction from content/message blocks
   - tool call extraction for card rendering
2. Refactor live background consumer to use this shared utility and render Human/AI as conversation cards.
3. Refactor history conversion to use the same shared utility for classification parity.
4. Verify parity and ensure tool/progress rendering remains stable.

## Validation

- Start a new thread and confirm Human/AI render as `UserMessage`/`AssistantMessage` cards.
- Recover same thread and confirm matching card behavior.
- Confirm tool cards still mount/update correctly in both paths.
- Confirm background consumer remains error-free in CLI logs.
