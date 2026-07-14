# IG-363: Intent classification prompt — static-first layout and XML inputs

## Purpose

Reorders the intent-classification LLM prompt so fixed instructions precede variable thread/runtime fields, and wraps the variable block in XML tags consistent with AgentLoop plan-style prompts (`<user>` / `<assistant>` conversation excerpts).

## Scope

- `packages/soothe/src/soothe/cognition/intention/prompts.py` — primary and retry templates
- `packages/soothe/src/soothe/cognition/intention/classifier.py` — conversation excerpt formatting for intent prompts
- Verification follow-ups: RFC-214 checkpoint load/save alignment, Plan prompt context blocks, executor subagent metrics on ledger path, serde allowlist, thread-continuation bootstrap guard

## Status

Completed: static-first intent prompts with ``<intent_instructions>`` / ``<intent_inputs>``; conversation excerpts as ``<user>`` / ``<assistant>`` (classifier); related fixes above so ``./scripts/verify_finally.sh`` passes.
