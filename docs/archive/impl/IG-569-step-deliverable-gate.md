# IG-569: Step Deliverable Gate (replace ## Result contract)

**RFC**: RFC-630
**Created**: 2026-07-08
**Status**: Done

## Problem

Execute action retry used a substring check for `## Result` in accumulated output. That
conflicts with free-form `ledger_direct` goal completion and caused false retries when
tools succeeded but the model omitted the markdown header (loop 3200: duplicate Result
sections after a misdirected retry pass).

## Solution

Replace the `## Result` contract with a **Step Deliverable Gate**:

1. **Structural** — Pass 2 `requires_tool_use`, final assistant text length, tool outcome
   metadata (RFC-211), tool budget / all-failed signals.
2. **Evidence** — When tools are required, at least one successful non-error outcome.
3. **Fast LLM assess** — Optional structured verdict when structural checks are
   inconclusive (`execute_deliverable_assess`: auto | always | never).

Retry nudges are **failure-mode-specific**; retry passes **replace** prior pass output
( no concatenation ).

## Changes

| Area | File |
|------|------|
| Gate logic | `packages/soothe/src/soothe/foundation/sloop/cognition/step_deliverable.py` |
| Remove legacy | Delete `simple_bypass.py` |
| Pass 2 field | `IntakePass2LLMResult.requires_tool_use` + prompt |
| Step metadata | `StepAction.requires_tool_use` |
| Executor retry | `executor.py` |
| Config | `execute_min_answer_chars`, `execute_deliverable_assess` |
| RFC | `RFC-630` §8.2, §8.5, execute retry section |

## Verification

- `./scripts/verify_finally.sh`
- Loop 3200 regression: curl + free-form weather answer → no retry
- Tool-less refusal when `requires_tool_use=True` → retry with contextual nudge
