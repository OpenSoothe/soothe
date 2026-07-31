# IG-668: Loop fa03 assess envelope stall + unbounded raw fallback

**Created**: 2026-07-31
**Status**: Complete
**Incident**: loop `019fb6ee-3669-7bb2-aac5-e2fd398dfa03` (`fa03`)
**Related**: IG-666 (planner json_schema methods), IG-653 (plan-phase wall clock), IG-503 (network retry)

## Problem

Loop `fa03` looked hung for ~12 minutes on its 5th turn. The worker was healthy and the
provider was healthy (a trivial `qwen3.6-flash` call answered in 1.6s). The whole stall
was one `assess` phase: `elapsed_ms=729036` for a call that normally takes 20-50s.

Three format failures, one after another — every response carried a usable assessment:

1. `15:25:45` structured attempt 1 returns bare `[]` → JSON root not an object.
   Already retriable, so the method retried (correct behavior).
2. `15:26:04` attempt 2 returns the right fields wrapped in an envelope,
   `{"PLAN_ASSESS": {...}}` → `'status' is a required property`. Structured path gives up.
3. `15:26:04-15:36:04` planner falls back to a raw un-schema'd `ainvoke`. `_ainvoke_bounded`
   inherits `agent.loop.llm_rate_limit` (`call_timeout_seconds: 600`, `max_timeout_retries: 10`),
   which is sized for execute-step calls. With no `response_format` and no `max_tokens`, the
   thinking model ran past 600s: **10 minutes of zero log output**.
4. `15:37:24` the retry returned in ~80s but as tag-wrapped YAML
   (`<PLAN_ASSESS>\nstatus: "continue"\n...`). `_parse_status_assessment_from_raw_message`
   does a plain `json.loads`, so it failed with `Expecting value: line 1 column 1`.

The planner then used its hard-coded default assessment and continued.

**Worst case was far worse than what happened.** Had the raw call kept timing out, the
escalation ladder (600, 720, 864, then 900 x 8 — 11 attempts) would have stalled the loop
for ~2h36m with no events at all.

Root cause is a tolerance gap, not a model-quality problem: `assess` was the only planner
phase invoking structured output with `normalize=None`, so it had no salvage hook, while
`generate` and `gap` already pass `coerce_*_wire_dict`.

## Fix

| Area | Change |
|------|--------|
| `status_assessment_wire.py` (new) | `coerce_status_assessment_wire_dict` — unwrap envelope, normalize enum case, drop unknown keys |
| `wire_envelope.py` (new) | `unwrap_schema_envelope` — shared single-key envelope peel, used by all three planner coercions |
| `plan_gap_wire` / `plan_generation_wire` | Peel the same envelope before salvage (identical exposure) |
| Planner `assess` | Pass `normalize=coerce_status_assessment_wire_dict` — envelope responses now validate instead of falling back |
| `_parse_status_assessment_from_raw_message` | Accept JSON, tag-wrapped bodies, and YAML mappings; run the payload through the coercion |
| `_assess_fallback_rate_limit_config` | Fallback bounded to 90s / no timeout retries (mirrors `_gap_llm_rate_limit_config`) |
| `_ainvoke_bounded` | Accepts `rate_limit_config` override, like `_invoke_structured` |
| Fallback model | `max_tokens` capped so an unconstrained thinking model cannot run away |

Effect on this incident: step 2 now validates, so the fallback is never reached. If it
were, the worst case drops from ~2h36m to 90s.

## Non-goals

- Planner-phase heartbeat. The executor emits `CoreAgent stream heartbeat` sentinels via
  the graph stream reader; the plan nodes have no equivalent, so long plan phases are
  invisible to the TUI. Bounding the fallback caps the visible silence, but a real
  heartbeat needs a separate change to the plan-node streaming path.
- Changing `plan_assess_model_role` away from `fast`. Model choice stays an operator call.
- Reusing the response the structured path already parsed. `StructuredOutputError` does not
  carry the offending payload, and attaching it means editing `soothe-nano` (submodule).
