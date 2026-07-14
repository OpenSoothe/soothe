# IG-380: Plan-phase ledger projection, execute fan-out policy, explore report

**Status:** Completed  
**Scope:** Deliverables **A**, **D**, and **E2** only (per approved plan). Not in scope: B, E1, AgentLoop-owned-subagent doctrine.

## A — Plan-phase ledger projection

**Problem:** `PromptBuilder.build_plan_messages` forwarded the full `state.loop_messages` ledger into every plan-assess and plan-generate call, inflating tokens and latency on long goals.

**Solution:** `PlanPromptLedgerConfig` under `agentic.plan_prompt_ledger` with:

- `plan_ledger_max_messages` (0 = unlimited)
- `plan_ledger_max_total_chars` (0 = unlimited)
- `plan_ledger_max_message_chars` (0 = unlimited per message)

[`plan_ledger_projection.py`](../../packages/soothe/src/soothe/core/prompts/plan_ledger_projection.py) builds a **read-only projection** (deep copies when limits apply). Persisted `loop_messages` are never mutated.

**Defaults:** All zeros in template (`config.yml`) for backward compatibility. `config.dev.yml` sets non-zero dev caps for local validation.

**References:** IG-372, IG-374, IG-377.

## D — Execute discovery fan-out

**Policy:** [`execution_policies.xml`](../../packages/soothe/src/soothe/core/prompts/fragments/system/policies/execution_policies.xml) extended with rules against parallel shallow directory scans on overlapping paths, preference for one recon then sequential reads, and `glob` cost awareness.

**Concurrency:** Template `max_parallel_steps` remains **16**. **Dev profile** [`config/config.dev.yml`](../../config/config.dev.yml) sets `max_parallel_steps: 8` to reduce worst-case parallel listing fan-out locally without changing production template defaults.

## E2 — Explore comprehensive delegate report

**Problem:** Explore’s final markdown was useful but light on parent-planning hints (next reads, coverage gaps).

**Solution:** Extend `ExploreResult` with `suggested_next_actions`, `coverage_gaps`, and `architecture_notes`; expand `SYNTHESIZE` prompt and `format_explore_result_markdown` to render new sections. Single markdown artifact for delegate parity (IG-356).

## Verification

Run `./scripts/verify_finally.sh` before merge.
