# IG-302 Goal Output Hard Cutover

> **Superseded (IG-317):** Core-loop final answers stream on LangGraph **`mode="messages"`** with **`phase`** (for example `goal_completion`). The interim plan below—final text only via **`soothe.output.goal_completion.*`** custom events and an SDK output registry—is **not** the current architecture.

## Original intent (archived)

- Hard cutover so CLI/TUI did not read final answer text from `AgenticLoopCompletedEvent` payloads alone.
- Push final prose through a dedicated output-domain event pair (`streaming` / `responded`) and registry-based extraction.

## What replaced it

- **IG-317** unifies assistant text on the **`messages`** wire with loop **`phase`**; see `docs/impl/IG-317-rfc614-loop-message-stream-unification.md` and `docs/specs/RFC-614-unified-streaming-messaging.md`.
- Registry-based `soothe.output.*` assistant extraction was removed from the SDK and clients.

## Git history

For the full original objective, scope, and completion criteria text, use git history on this file before the IG-317 documentation consolidation.
