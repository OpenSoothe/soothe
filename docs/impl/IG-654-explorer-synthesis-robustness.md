# IG-654 Explorer Synthesis Robustness

## Background

Explorer relies on strict structured synthesis into `ExploreResult`. In production runs,
provider outputs may occasionally omit required fields (for example `matches`), which
causes strict schema validation to fail and forces a partial fallback even when findings
are otherwise sufficient.

This degrades user experience by:

- showing partial status too often for successful discovery runs,
- triggering repeated explorer delegations from parent steps,
- reducing determinism across providers and model hops.

## Goals

- Improve explorer synthesis stability across provider structured-output quirks.
- Preserve strict schema guarantees at middleware boundaries.
- Keep current partial fallback path as last-resort safety net.

## Non-goals

- Changing explore tool execution strategy.
- Reworking TUI card lifecycle.
- Disabling strict schema validation globally.

## Design

### 1) Structured normalization before strict validation

Add an explorer-specific normalizer used by structured synthesis invocation.

Responsibilities:

- coerce alternate payload keys (`items`, `results`) into `matches`,
- ensure required keys exist (`target`, `matches`, `summary`),
- sanitize match entries (`path`, `description`, `relevance`, `snippet`),
- cap returned matches by configured `max_matches`.

This follows existing `normalize=` usage patterns in planner and veritas flows.

### 2) Retry on structured synthesis validation failures

Introduce bounded retries for synthesis when `StructuredOutputError` occurs.

- attempt base synthesis first,
- append a compact repair hint for retry attempts,
- retry using the same synthesis model up to configured retries.

### 3) Optional fallback to primary model for synthesis

When configured, if retries on the fast synthesis model are exhausted,
retry synthesis once on the primary explore model before returning partial.

### 4) Prompt tightening for required fields

Update synthesis prompt contract to explicitly require all required `ExploreResult`
keys and `matches: []` when no match exists.

## Config additions

`ExploreSubagentConfig`:

- `synthesis_validation_retries` (default: `1`)
- `synthesis_fallback_to_primary_model` (default: `true`)

## Validation plan

Unit tests:

- normalizer coercion for malformed payloads,
- async synthesis retry after first structured failure,
- synthesis fallback to primary model when fast model fails.

## Risks

- Over-coercion hiding true model regressions.
  - Mitigation: keep strict final validation and preserve explicit failure reason in logs.
- Additional synthesis latency from retries.
  - Mitigation: bounded retries and optional fallback flag.
