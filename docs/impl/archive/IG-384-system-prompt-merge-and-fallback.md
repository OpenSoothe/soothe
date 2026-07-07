# IG-384: System prompt optimization + prompts module merge

## Scope

1. **Merge** `packages/soothe/src/soothe/config/prompts.py` into `packages/soothe/src/soothe/core/prompts/system_templates.py`; config package re-exports unchanged public names.
2. **CoreAgent system message**: when `routing_classification` / `unified_classification` is absent, apply **medium**-tier optimized prompt (ENVIRONMENT + static/dynamic sections) instead of skipping optimization.
3. **Execution hints**: append the `Execution hints:` suffix from `state["system_prompt"]` onto the optimized system message so Layer 2 hints are not dropped when middleware replaces `system_message`.
4. **Intent / scenario**: pass `intent_type` into graph state from the runner and AgentLoop execute path so IG-268 dynamic scenario text can use real intent; map optional `synthesis_scenario` to goal-type hints when present on state.
5. **Langfuse (IG-385)**: `SootheLangfuseCallbackHandler` + a context hint from `SystemPromptOptimizationMiddleware` so generation traces include the effective CoreAgent system prompt when LangChain’s traced batch would otherwise omit it.

## Files

- `core/prompts/system_templates.py` — former `config/prompts.py` content.
- `soothe.config` continues to re-export `_DEFAULT_SYSTEM_PROMPT`, `_SIMPLE_SYSTEM_PROMPT`, `_MEDIUM_SYSTEM_PROMPT`, `_TOOL_ORCHESTRATION_GUIDE` from `soothe.core.prompts`.

## Status

Complete after verification.

## Verification

Run `./scripts/verify_finally.sh` before commit.
