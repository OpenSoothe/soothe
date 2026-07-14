# IG-272: Unified Daemon → Client Streaming Framework Implementation

**Status**: Superseded (IG-317 + RFC-614 refresh)  
**Date**: 2026-04-27  
**RFC Reference**: RFC-614 (Unified Streaming Messaging)

## Summary

This IG originally tracked implementation phases for RFC-614, including early drafts of:

- an SDK **`output_events`** registry (`register_output_event`, `extract_output_text`),
- runner helpers that re-wrapped AI chunks as **`soothe.output.goal_completion.*`** (and similar) custom events,
- client branches keyed on those **`soothe.output.*`** types.

**IG-317** replaced the assistant-text path: user-visible loop answers are loop-tagged LangGraph **`mode="messages"`** payloads with a **`phase`** field. Public SDK surface for recognition lives in `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py`. The registry and duplicate custom-event assistant wire described in long-form drafts of this IG are **gone** from the codebase.

## Where to read the current design

| Topic | Location |
|-------|-----------|
| Streaming + suppression contract | `docs/specs/RFC-614-unified-streaming-messaging.md` |
| Loop message unification | `docs/impl/IG-317-rfc614-loop-message-stream-unification.md` |
| Daemon forwarding matrix | `docs/analysis/daemon-event-forwarding-matrix.md` |
| Client accumulation | `packages/soothe-cli/src/soothe_cli/shared/event_processor.py` |
| Phase constants / helper | `packages/soothe-sdk/src/soothe_sdk/ux/loop_stream.py` |

## Archive

Detailed multi-phase plans, pseudocode, and worked examples in the pre-IG-317 version of this IG referenced removed APIs (`is_output_event`, `soothe.output.execution.streaming`, etc.). That content was **deleted here on purpose** so the IG cannot be mistaken for an active implementation spec. Retrieve it from git history if needed for archaeology.
