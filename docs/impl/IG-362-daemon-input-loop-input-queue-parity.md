# IG-362: Daemon input vs loop_input queue field parity

## Status

Complete.

## Problem

`MessageRouter` normalizes `max_iterations`, `preferred_subagent`, `model`, and `model_params` when handling `type: "input"`, but `_handle_loop_input` passed these fields through raw from `msg`. That allowed invalid types into the same internal input queue and diverged from the primary input path.

## Approach

- Add `_queue_options_from_daemon_message()` to centralize normalization.
- Use it for both `input` and `loop_input` branches when building the internal queue payload.

## Verification

Run `./scripts/verify_finally.sh` after code changes.
