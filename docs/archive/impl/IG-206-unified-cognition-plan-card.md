# IG-206: Unified cognition plan card (assessment + plan + action)

## Goal

Expose phase-1 and phase-2 plan reasoning separately on the wire, show `plan_action` (keep/new), and render one TUI card with a single `StreamDisplayPipeline.process()` call for deduplication (then `continue` so the event is not formatted twice).

## Changes

### Wire (`packages/soothe`)

- `PlanResult`: `assessment_reasoning`, `plan_reasoning`; `reasoning` remains the combined chain for backward compatibility.
- `LLMPlanner._combine_results`: fills both phase fields and combined `reasoning` (`assessment [Plan] plan` when both present).
- `agent_loop` `"plan"` yield: includes `assessment_reasoning`, `plan_reasoning` (plus existing fields).
- `LoopAgentReasonEvent` + `_runner_agentic` mapping: same fields for `soothe.cognition.agent_loop.reasoned`.

### CLI (`packages/soothe-cli`)

- `format_judgement`: optional `plan_action` → `[keep]` / `[new]` prefix.
- `format_plan_phase_reasoning`: labeled Assessment / Plan lines.
- `StreamDisplayPipeline._on_loop_agent_reason`: labeled sections when structured fields present; else legacy `reasoning` line.
- TUI: `CognitionPlanReasonMessage` (`$cognition` border); `textual_adapter` intercepts `LOOP_REASON_EVENT_TYPE` after step handlers; `MessageType.COGNITION_PLAN` + `MessageData` fields; `app._mount_message` union updated.

## Verification

- `./scripts/verify_finally.sh`
