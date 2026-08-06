# IG-676 Fresh Special Entry + Mid-Loop Intake Tiers

## Context

StrangeLoop preprocess routing was a product of two axes (intake ×
fresh/continuation), which duplicated the mid-loop spine and made
continuation+simple/trivial jump straight to `evaluate` while complex entered
`gather_evidence`. After IG-675, simple/complex already skip the
continuation-assess LLM inside evaluate — the preprocess overlay no longer
earns its complexity.

Principle:

1. **Fresh goal** = only special *graph entry* (inject / skip-evaluate).
2. **Mid-loop** (new goal after prior work, and iter≥1) = one default spine
   entry (`gather_evidence`), with **intake-tiered** work inside stations.

```text
trivial < simple < complex
```

## Goals

- Collapse continuation intake matrix at `route_after_preprocess`: all
  non-fresh → `gather_evidence`.
- Codify mid-loop policy helper for trivial / simple / complex
  (skip continuation-assess, lightweight generate, inventory allow).
- Surface `is_fresh_goal` from `enter_loop` for preprocess routing and inject.
- Prune unused ENTER_LOOP targets (`CHECK_LIMITS`, `GENERATE_PLAN`).
- Unify synthetic `StatusAssessment` factories (fresh bypass + forced generate).

## Mid-loop intake policy

| Intake | New mid-loop goal | Mid-iteration |
|--------|-------------------|---------------|
| trivial | gather → evaluate: continuation-assess / keyword bootstrap | No inventory; status assess |
| simple | gather → evaluate: skip assess LLM → lightweight generate | Inventory when evidence; lightweight generate |
| complex | gather → evaluate: skip assess LLM → full generate | Inventory + assess + full generate; structural keep |

## Fresh-only specials (unchanged)

| Behavior | Path |
|----------|------|
| trivial/simple inject | enter_loop → commit_plan |
| complex skip evaluate | gather → generate |
| chitchat / wired | END / delegate |

## Out of scope

- Restoring fresh simple → lightweight generate (still collapsed with trivial inject).
- Cheaper mid-iteration assess model for trivial.
- Pass1/Pass2 merge.

## Related

- [IG-675](IG-675-continuation-simple-skip-assess.md) — skip assess LLM for simple
- [IG-551](../archive/impl/IG-551-mid-loop-continuation-planning-coordination.md) — coordination history
- [IG-590](../archive/impl/IG-590-continuation-simple-bootstrap-and-single-pass-plan-bias.md) — superseded for preprocess overlay

## Validation

- Route truth table: continuation × trivial/simple/complex → `gather_evidence`
- Fresh trivial/simple → `commit_plan`; fresh complex → `gather_evidence`
- Mid-loop policy unit tests (skip assess / lightweight / inventory)
- Continuation+trivial bootstrap still works via evaluate after gather
- Shared `has_prior_goal_context` / `is_fresh_goal` / `is_fresh_loop_skip_evaluate`
- `./scripts/verify_finally.sh`
