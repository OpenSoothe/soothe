# IG-674: Execute-Step Vision Context (Image Understanding Without Over-Scope)

## Goal

Preserve daemon vision-preflight image facts on StrangeLoop **execute-step**
prompts without injecting the full parent `GOAL` (which causes step over-execution).

## Motivation

Daemon IG-327 converts pasted `attachments` into enriched goal text:

```text
<user text>

--- Vision summary ---
...
---
```

Plan-generate sees that `GOAL`, but execute-step envelopes use only
`step.full_description` / `description` as `EXECUTION TASK`. Wire plan steps are
short (<20 words); `synthesize_full_description` deliberately omits the overall
goal (IG-508). Image facts are therefore lost before CoreAgent runs.

Injecting the full original `GOAL` into execute would reintroduce scope confusion
(`GOAL` vs `EXECUTION TASK`) and push multi-step waves to over-execute.

## Design

| Piece | Choice |
|-------|--------|
| Package | `soothe` (host StrangeLoop) |
| Daemon / TUI | Unchanged (preflight + attachments stay as today) |
| Extractor | Parse structured `--- Vision summary ---` … `---` delimiter only |
| Execute envelope | New subordinate `VISION CONTEXT` section (not `GOAL`) |
| Scope guard | Extra INSTRUCTIONS lines when vision context is present |
| Plan briefs | Optional: append capped “Image facts: …” into synthesized `full_description` when goal has a vision block |
| Hydrator | Prompt note: copy concrete vision facts; do not restate whole user request |

### Envelope shape (execute)

```text
EXECUTION TASK:
<step brief>                         ← sole work unit

VISION CONTEXT:
<vision summary body>                ← background image facts only

EXPECTED OUTPUT: ...
INSTRUCTIONS:
- Complete only this step's deliverable; ...
- EXECUTION TASK is authoritative scope; VISION CONTEXT is background only
- Use VISION CONTEXT facts ... instead of inventing image content
- Do not expand work to cover the entire original user request
...
```

### Non-goals

- Passing raw `attachments` / multimodal blocks into CoreAgent execute.
- Injecting parent `GOAL:` into `build_execute_step_message`.
- Keyword heuristics on user prose to detect images (delimiter / attachments only).
- Changing `image_to_text` / `ocr` intent-hint multimodal turns.

## Files

- `packages/soothe/src/soothe/sloop/vision_context.py` — extract / cap / instruction helpers
- `packages/soothe/src/soothe/sloop/prompts/user_message.py` — `vision_context` kwarg on execute envelope
- `packages/soothe/src/soothe/sloop/engine/executor.py` — compose path wires extractor
- `packages/soothe/src/soothe/sloop/cognition/plan_step_briefs.py` — vision facts in synthesized briefs
- `packages/soothe/src/soothe/sloop/cognition/planner.py` — pass `goal=` into populate
- `packages/soothe/src/soothe/sloop/engine/step_brief_hydrator.py` — hydration prompt note
- Unit tests under `packages/soothe/tests/unit/`

## Validation

- Extractor unit tests (present / absent / capped)
- Execute envelope: has `VISION CONTEXT`, no `GOAL:`, instructions present
- Brief synthesizer includes image facts when goal has vision block
- `./scripts/verify_finally.sh`
