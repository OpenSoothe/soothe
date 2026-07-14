# IG-540: Intent-Classify Prompt and Ledger Optimization

## Summary

Optimize intake classification by moving static rules to the system message, injecting
prior goal completion (ledger-direct or synthesized) into the human message, and
recording intent-classify Human/AI pairs in the CE ledger.

## Scope

- Split `intake_classification*.xml` into system + human fragments
- System prompt carries static rules + `<TIMESTAMP>` footer
- Prior goal completion via ledger projection (not inline human injection)
- Ledger phase `intent_classify`; include in new-goal plan projection
- Langfuse: intent-classify and `strange-loop-graph` share one trace via per-goal handler with pinned `trace_context.trace_id` (Langfuse opens a new trace per invocation even when reusing the cached handler)
- Human envelope adds `TASK:` section (plan-assess pattern) restating reasoning output contract at invoke time
- System prompt leads with output contract; label definitions renamed to avoid "single focused step" bleed into reasoning

## Status

Implemented (prompt-only; no post-LLM reasoning polish).
