# IG-325: Thread continuation — classification prompt + plan bootstrap

## Status

Completed — intent prompt precedence (IG-325) and first-plan bootstrap for `thread_continuation` without new config.

## Goals

1. **Intent (LLM only)**: Improve [`INTENT_CLASSIFICATION_PROMPT`](../../packages/soothe/src/soothe/cognition/intention/prompts.py) so explicit user instructions (new standalone task, ignore prior context, etc.) win over default thread continuation when conversation context exists.
2. **Plan bootstrap**: When the classifier returns `thread_continuation` and loop state is a true first plan of the run (iteration 0, no step results, safe checkpoint semantics), skip the first `LoopPlanner` LLM call and inject a single-step synthetic [`PlanResult`](../../packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py).

## Non-goals

- No new YAML or `SootheConfig` fields.
- No keyword/substring gates in code for these paths (including `force_keywords`).
- No query-length or word-count heuristics for routing.
- No skipping `classify_intent` — every turn still runs structured intent classification.

## Safety: when bootstrap is allowed

Structural checks only (see `thread_continuation_bootstrap` module):

- `intent_type == "thread_continuation"`.
- `state.iteration == 0` and `state.step_results` is empty.
- If resuming a **running** checkpoint with a valid `GoalExecutionRecord`, bootstrap is **disallowed** when that record already advanced (`iteration > 0` or non-empty `reason_history` / `act_history`).

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- RFC-201 (agentic loop)
- IG-226 / IG-284 (intention module)
