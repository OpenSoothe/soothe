# IG-317: RFC-614 assistant output — `LoopAIMessage` + `stream_event` unification

**Status:** In progress  
**Normative spec:** [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) (updated in this change train)

## Summary

Unify all user-visible assistant text streaming on the LangGraph **`messages`** wire shape (`stream_event` progress tuples in AgentLoop; runner yields `(namespace, mode, data)` with `mode="messages"`), using **`LoopAIMessage`** / **`LoopAIMessageChunk`** and a **`phase`** field so clients and the daemon can apply IG-119 / IG-304 suppression correctly without a parallel `soothe.output.goal_completion.streaming` path.

## Motivation

- `goal_completion_stream` + outer envelope broke `full_output` accumulation (`iter_messages_for_act_aggregation` never saw `mode=="messages"`).
- Duplicate protocols (`_wrap_streaming_output` → custom dicts) complicate `agentic.output_streaming: false` and SDK registration.

## Scope

- **In:** AgentLoop synthesis, `_runner_agentic` forwarding, chitchat/quiz/autonomous assistant payloads, `stream_normalize` accumulators, CLI/SDK consumption, RFC-614 + forwarding matrix.
- **Out:** Non-assistant `custom` events (thread lifecycle, plan steps, errors).

## Implementation notes

- Phase literals include `goal_completion`, `chitchat`, `quiz`, `autonomous_goal` for assistant-output paths; execute-phase CoreAgent AI messages remain untagged plain `AIMessage` (suppressed at runner except tool metadata).
- `SynthesisGenerator` receives optional `SootheConfig` for evidence budgeting via `report_output`.

## Verification

Run `./scripts/verify_finally.sh` before merge.
