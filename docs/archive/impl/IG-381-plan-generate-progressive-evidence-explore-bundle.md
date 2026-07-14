# IG-381: Progressive plan generation, supportive_evidence, explore bundling

**Status:** Superseded by IG-399  
**Scope:** Prompt + schema only (AgentLoop plan-generate path).

## Problem

1. Plan-generate could emit over-detailed multi-step plans before any execute evidence existed.  
2. Read-heavy exploration was sometimes fragmented across many root-level steps instead of batched explore subagents.

## Solution

1. **Progressive planning (prompt):** Instruct the model to keep early waves minimal when the ledger lacks tool/subagent results; add detail only after evidence accumulates.  
2. **`supportive_evidence` (schema):** Optional per-step string on `StepAction` citing which ledger facts justify that step (empty or explicit when no evidence yet).  
3. **Explore bundling (prompt):** Extend execution policies to prefer consolidating related readonly exploration into one or few `subagent: explore` steps.

## Files

- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py` — `StepAction.supportive_evidence`  
- `packages/soothe/src/soothe/core/prompts/fragments/instructions/plan_generate_instructions.xml`  
- `packages/soothe/src/soothe/core/prompts/fragments/system/policies/execution_policies.xml`  
- `packages/soothe/tests/unit/core/prompts/test_plan_generate_fragment_ig381.py`

## Verification

Run `./scripts/verify_finally.sh` before merge.

## Supersession

IG-399 removes progressive planning/supportive-evidence requirements and replaces them with:
- split plan nodes (`plan_assess` -> `plan_pre_generate` -> `plan_generate`)
- bounded pre-generate evidence probes (max three readonly probes)
- flattened `PlanGeneration` schema fields (no nested `decision` payload)
