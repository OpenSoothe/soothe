# IG-262: Friendly Goal Message via Intent Classification

**Status**: ✅ Completed
**Date**: 2026-04-25
**Scope**: Goal message display, intent classification

---

## Problem

User goal queries are displayed as raw text with minimal formatting:
- Input: "read 10 lines of project readme"
- Display: "read 10 lines of project readme"

This feels impersonal and lacks context about what the agent will actually do.

---

## Goal

Display friendly, action-oriented goal messages that reassure users:
- Input: "read 10 lines of project readme"
- Display: "I will read the project readme files and show the first 10 lines"

---

## Approach

Piggyback friendly message generation on the **existing intent classification LLM call** (zero extra latency).

The intent classification call already:
1. Normalizes the goal description for GoalEngine
2. Understands the task context and conversation

We add a **third output**: friendly user-facing message.

---

## Implementation Plan

### Phase 1: Model and Prompt Updates

1. **Add `friendly_message` field** to `IntentClassification`:
   ```python
   friendly_message: str | None = Field(
       default=None,
       description="User-friendly reinterpretation of the task (for display)"
   )
   ```

2. **Update classification prompts** to request friendly message:
   - Add instruction: "For new_goal: generate friendly_message (action-oriented, 1-2 sentences)"
   - Example: "I will read the project readme files and show the first 10 lines"

### Phase 2: Event Emission Updates

3. **Update goal creation events** to include friendly message:
   - `GoalCreatedEvent` already has `description` (normalized)
   - Add `friendly_message` field to event data

4. **Update goal display logic**:
   - `format_goal_header()` receives friendly_message if available
   - Falls back to goal.description if friendly_message is missing

### Phase 3: Verification

5. **Run verification suite**:
   ```bash
   ./scripts/verify_finally.sh
   ```

---

## Design Decisions

### Why Piggyback on Intent Classification?

| Alternative | Latency | Cost | Quality |
|------------|---------|------|---------|
| **Piggyback on intent classification** | **+0ms** | **+0 tokens** | **High (LLM context)** |
| Separate LLM call after classification | +2-4s | +500 tokens | High |
| Template-based generation | +0ms | +0 tokens | **Low (no context)** |

**Winner**: Piggyback approach (zero extra latency, full LLM context understanding).

### Why Only for `new_goal` Intent?

- `chitchat`: Has `chitchat_response` (already friendly)
- `quiz`: Has `quiz_response` (already friendly)
- `thread_continuation`: Reuses existing goal (no new message)
- `new_goal`: **Needs friendly message** (creating new goal)

### How to Handle Missing `friendly_message`?

Fallback chain:
1. Use `friendly_message` if present
2. Fall back to `goal.description` (normalized)
3. Fall back to raw user input (last resort)

---

## Files to Modify

| File | Change |
|------|--------|
| `packages/soothe/src/soothe/cognition/intention/models.py` | Add `friendly_message` field |
| `packages/soothe/src/soothe/cognition/intention/prompts.py` | Add friendly message instructions |
| `packages/soothe/src/soothe/cognition/intention/classifier.py` | Patch missing `friendly_message` |
| `packages/soothe/src/soothe/core/runner/_runner_autonomous.py` | Emit friendly message in events |
| `packages/soothe/src/soothe/core/event_catalog.py` | Add `friendly_message` to GoalCreatedEvent |
| `packages/soothe-cli/src/soothe_cli/cli/stream/pipeline.py` | Extract friendly message from events |
| `packages/soothe-cli/src/soothe_cli/cli/stream/formatter.py` | Format friendly message |

---

## Testing Strategy

1. **Unit tests**: Intent classification model validation
2. **Integration tests**: Goal creation → event emission → display
3. **Manual testing**: Verify friendly messages in CLI/TUI

Example test cases:
- "read 10 lines of readme" → "I will read the readme file and show the first 10 lines"
- "count all markdown files" → "I will count all markdown files in the project"
- "search for authentication code" → "I will search for authentication-related code in the codebase"

---

## Rollback Plan

If issues arise:
1. Remove `friendly_message` field from model
2. Remove prompt instructions
3. Display falls back to goal.description automatically

No breaking changes - backward compatible fallback.

---

## Success Metrics

- **Latency**: No increase in classification time (measured via logs)
- **User satisfaction**: Friendly messages displayed for 90%+ new_goal intents
- **Quality**: Messages are action-oriented and context-aware (manual review)

---

## References

- IG-226: Intent classification implementation
- IG-250: Quiz intent addition
- RFC-200: Agentic goal execution