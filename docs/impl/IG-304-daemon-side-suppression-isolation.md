# IG-304: Daemon-side Suppression Isolation for Agentic Output

> **Update (IG-317):** Final user-facing answer text is forwarded on the **`messages`** wire with **`phase`**, not via `soothe.output.goal_completion.responded`. Daemon-side suppression goals below still apply to execute-phase prose.

## Context

`case1.log` shows intermediate execute-phase assistant prose (for example, "Step 1 Complete ...")
being emitted in final CLI output. Current behavior relies on client-side suppression/accumulation
to hide intermediate text, which can still leak concatenated fragments and break final formatting.

## Problem

- Execute-phase `AIMessage` prose is forwarded from daemon and filtered in clients.
- Client suppression buffers mixed execution + synthesis text, then flushes at completion.
- This creates malformed final markdown and duplicated intermediate details.

## Goal

Move suppression responsibility to daemon emission paths so clients receive only:

1. progress/tool events for observability, and
2. explicit final goal completion output events for user-facing answer text.

## Scope

- Update daemon-side agentic stream forwarding to stop emitting execute-phase assistant prose
  as user-visible output payloads.
- Keep tool call/result stream forwarding intact for CLI/TUI activity display.
- Preserve explicit final output delivery via loop-tagged **`messages`** chunks (`phase`, including `goal_completion`).
- Add/adjust tests to enforce daemon-side isolation contract.

## Non-goals

- Rewriting the full client renderer architecture.
- Removing all client suppression logic in this change.

## Verification

- Targeted unit tests for daemon event contract and goal completion behavior.
- Relevant CLI/EventProcessor tests for streaming/batch expectations.
