# IG-640: Enter Shortcut to Run Queued Goal Head

**Created**: 2026-07-13  
**Status**: Implemented  
**Related**: [IG-632](IG-632-cancel-queued-goal-lifecycle.md), [IG-544](IG-544-tui-step-flow-and-plan-quick-view.md)

---

## Executive Summary

When a goal is running and more goals are queued, pressing Enter on an empty chat prompt now cancels the running goal and immediately advances execution to the queued head. Remaining queued goals stay in FIFO order.

This reuses the existing queue-preserving interrupt path (`discard_queue=False`) so behavior stays consistent with Ctrl+C while reducing friction for "run next goal now" workflows.

---

## Scope

### P0 - Enter shortcut trigger

- Add a reusable app-level predicate to detect whether Enter should run queued head now:
  - agent turn is running,
  - queue is non-empty,
  - queue head is a normal user goal,
  - chat input has no pending content (empty text, normal mode, no completion popup).
- Add a reusable app-level trigger that starts queue-preserving interruption and returns whether it fired.

### P0 - Chat input integration

- Wire `ChatTextArea` Enter handling so empty Enter attempts the new trigger first.
- Preserve existing behavior:
  - Enter with non-empty text still submits message.
  - Empty Enter remains a no-op when shortcut is not eligible.

### P1 - Plan quick-view affordance

- Update plan quick-view header to display an Enter hint when the shortcut is currently available.

---

## Files

- `packages/soothe-cli/src/soothe_cli/tui/app/_messages_mixin.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/chat_input.py`
- `packages/soothe-cli/src/soothe_cli/tui/widgets/plan_quick_view_overlay.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_quit_pending.py`
- `packages/soothe-cli/tests/unit/ux/tui/test_plan_quick_view_overlay.py`

---

## Behavior Notes

- The new Enter shortcut intentionally mirrors Ctrl+C's queue-preserving semantics by calling the same interruption path with `discard_queue=False`.
- Queue processing still flows through `_process_next_from_queue()` cleanup, so only the queue head is promoted and the tail remains queued.

---

## Verification

```bash
pytest -q packages/soothe-cli/tests/unit/ux/tui/test_quit_pending.py \
          packages/soothe-cli/tests/unit/ux/tui/test_plan_quick_view_overlay.py
```
