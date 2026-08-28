# IG-768: Clarification Failure Fallback — TUI Auto→Manual & Autopilot LLM Retry

## Problem

When veritas fails to answer a clarification in auto mode:

- **TUI (human attached)**: Only `structured_output_failed` and (when
  `degrade_to_manual_on_low_confidence=True`) `low_confidence` fall back to the
  interactive relay. `answer_was_question` and `explicit` hard-defer, parking
  the loop with no ask widget — the user sees a "pending" step with no way to
  respond.

- **Autopilot (headless)**: All veritas failures hard-defer, parking the goal
  in `awaiting_clarification` status. No human is available to answer
  out-of-band, so the goal stalls indefinitely. The LLM never gets a chance to
  try a different action.

## Solution

### Part 1: TUI — all veritas failures degrade to manual

Extend `_DEFER_TABLE` so every `DeferKind` with an `interactive_fallback`
wired routes to the human relay instead of hard-defering. The
`degrade_low_confidence` flag is replaced by a broader
`degrade_to_manual_on_failure` flag (default `True`) that applies to all
veritas failure kinds.

| DeferKind | `degrade_to_manual_on_failure=True` + fallback | `degrade_to_manual_on_failure=False` |
|---|---|---|
| `structured_output_failed` | → interactive relay (unchanged) | hard defer |
| `low_confidence` | → interactive relay (was conditional) | hard defer |
| `answer_was_question` | → interactive relay (new) | hard defer |
| `explicit` | → interactive relay (new) | hard defer |

When no fallback is wired (autopilot), all kinds still hard-defer — but Part 2
changes what "defer" means for autopilot.

### Part 2: Autopilot — veritas failure returns a synthetic "retry" answer

When `interactive_fallback is None` (no human) and veritas fails, instead of
raising `ClarificationDeferredError` (which parks the goal), return a
synthetic `ClarificationAnswer` with `source="retry"` and a sentinel answer
that tells the originating execute node to let the LLM try again.

The sentinel answer is `"(retry)"` — the execute node's clarification-resume
path already feeds answers back to the CoreAgent as tool results. A
`"(retry)"` answer signals "I couldn't answer this; please try a different
approach" to the LLM, which naturally produces a new action.

This is controlled by a new config flag:
`agent.clarification.autopilot_retry_on_fail` (default `True`).

When `False`, autopilot keeps the old hard-defer behavior.

## Changes

### `packages/soothe/src/soothe/sloop/clarification/auto.py`
- Replace `_DEFER_TABLE` with a simpler model: all kinds fall back when
  `degrade_to_manual_on_failure` is True and a fallback exists.
- Add autopilot retry path: when no fallback and
  `autopilot_retry_on_fail=True`, return synthetic `ClarificationAnswer(source="retry")`.
- Rename `degrade_low_confidence` → `degrade_to_manual_on_failure` (keep
  backward-compat property alias).

### `packages/soothe/src/soothe/config/models.py`
- `ClarificationConfig.degrade_to_manual_on_low_confidence` →
  `degrade_to_manual_on_failure` (default `True`).
- Add `autopilot_retry_on_fail: bool = True`.

### `packages/soothe/src/soothe/sloop/clarification/runtime_factory.py`
- Pass new flags through.

### `packages/soothe/src/soothe/sloop/clarification/selector.py`
- Pass new flags through.

### Tests
- `test_auto.py`: update existing tests; add TUI all-kinds-degrade and
  autopilot retry tests.
- `test_await_clarification.py`: add autopilot retry path test.
