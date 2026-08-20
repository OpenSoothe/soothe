# IG-728: LLM LoopRail auto-pick on submit

**Created**: 2026-08-08  
**Status**: Implemented  
**Related**: [RFC-231 §10](../specs/RFC-231-looprail-rail-exec.md),
[RFC-228](../specs/RFC-228-autopilot-job-ipc.md) (`job_create` / `rail_id`),
[RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md)
(no keyword content judgment — project Critical Rule 9),
design draft
[2026-08-08-llm-rail-auto-pick-design.md](../drafts/2026-08-08-llm-rail-auto-pick-design.md),
[IG-678](../archive/impl/IG-678-autopilot-ce-rails-production-readiness.md)
(deterministic selector baseline)

---

## Goal

When Autopilot job submit omits `rail_id` / `--rail`, resolve a LoopRail via
**structured light-LLM** match against the **merged three-tier catalog**
(`summary` + `applies_when`), then fall back to `.rail-default` /
`default_rail` / no rail. Bind before `job_start`. Never invent `default.yml`.

---

## Background

Before this IG, `resolve_rail_id` was deterministic only (explicit →
`.rail-default` → config → none). Catalog YAML already carried `summary` /
`applies_when`; home/workspace rails update externally. RFC-231 §10 now
specifies the full cascade including structured LLM auto-pick.

---

## Design rules (MUST)

1. **Cascade**: explicit → LLM (if enabled) → `.rail-default` →
   `default_rail` → `None` (RFC-231 §10.1).
2. **RFC-630**: no keyword/regex scoring of job text; structured pick only.
3. **Dynamic candidates**: `LoopRailCatalog(workspace).load_all()` after deny /
   `auto_pick: false` filter — never hardcode builtin names in the system prompt.
4. **Prompt split**: stable system policy + `<catalog_data>` cards + job in
   `<untrusted_data>` (guards security posture).
5. **Validate** model `rail_id ∈ allowed ∪ {null}`; unknown → fallback.
6. **Await** pick on submit before `_bind_rail_for_job`; timeout/error →
   fallback; do not fail submit solely for auto-pick failure.
7. **Roots only**: set `rail_id` when `parent_id is None`.
8. **No verb selection**: picker sets root `rail_id` only; flow advancement
   stays deterministic LoopRail.
9. **Config sync**: `config/soothe.template.yml`, develop copy, daemon setup
   templates (`AGENTS.md` Critical Rule 2).

---

## Deliverables

### P0 — Config + catalog fields

- [x] `AutopilotConfig` fields: `rail_auto_pick`, `rail_auto_pick_min_confidence`,
      `rail_auto_pick_model_role`, `rail_auto_pick_timeout_s`,
      `rail_auto_pick_deny`, `rail_auto_pick_max_candidates`,
      `rail_auto_pick_skip_if_workspace_default`,
      `rail_auto_pick_abstain_overrides_defaults`
- [x] Sync templates (`soothe.template.yml`, develop, daemon setup)
- [x] Optional rail YAML `auto_pick: bool` (default true) on `RailDefinition` /
      catalog load
- [x] Builtin `greenfield-system` has `auto_pick: false` (SoT); deny list is
      for optional operator extras only

### P1 — Picker + cascade

- [x] `RailAutoPickResponse` / `RailPickResult` models
- [x] `format_rail_pick_user_prompt` (+ system constant)
- [x] `RailAutoPicker.pick(description, candidates) -> RailAutoPickResponse`
      via `invoke_structured_chat_typed` (same family as `LLMGuardEvaluator`)
- [x] `async resolve_rail_for_job(...)` implementing §10.1 cascade
- [x] Keep sync `resolve_rail_id` as deterministic helper
- [x] Caps: field truncation; over `max_candidates` → skip LLM

### P2 — Submit wiring + observability

- [x] `AutopilotService.submit_task` awaits `resolve_rail_for_job` before bind
- [x] Model from `rail_auto_pick_model_role` or `monitor_model_role` (daemon);
      service accepts `auto_pick_model` (falls back to consensus model)
- [x] INFO log: `source`, `rail_id`, `confidence`
- [x] Persist pick metadata as `jobs/{job_id}/rail_selection.json`
      (`soothe.autopilot.jobs.rail_selection`)
- [x] Align `builtin_rails/README.md` with real auto-pick behavior

### P3 — Tests

- [x] Unit: cascade (explicit / high conf / low conf / abstain / deny / timeout /
      no model / skip_if_workspace_default)
- [x] Unit: unknown model id → fallback
- [x] Unit: `auto_pick: false` + deny omitted from candidates
- [x] Unit: formatter 0 / 1 / N custom rails
- [x] Unit: `max_candidates` exceeded → skip LLM
- [x] Integration: mock structured model → submit binds rail + `job_start`
- [x] `test_rail_auto_pick.py` + `test_rail_bind.py` submit auto-pick case

---

## Out of scope

- Async `rail_pending` bind (v2)
- Mid-job re-pick
- LLM choosing next `then:` verbs
- Keyword shortlist before LLM
- Changing CE / StrangeLoop ownership

---

## Suggested defaults

```yaml
agent:
  autopilot:
    rail_auto_pick: true
    rail_auto_pick_min_confidence: 0.6
    rail_auto_pick_model_role: null
    rail_auto_pick_timeout_s: 12
    rail_auto_pick_deny: []
    rail_auto_pick_max_candidates: 32
    rail_auto_pick_skip_if_workspace_default: false
    rail_auto_pick_abstain_overrides_defaults: true
```

---

## Cleanse (post-impl)

- Shared `_deterministic_fallback` for sync `resolve_rail_id` and async cascade
- Persist helper moved to `autopilot/jobs/rail_selection.py` (selector stays
  resolution-only)
- Dropped `getattr` backward-compat shims on new config fields
- Greenfield exclusion SoT = YAML `auto_pick: false` (empty default deny list)
- Deduped `resolve_rail_id` unit tests into `test_rail_auto_pick.py`
- Trimmed package `__init__` exports (`RailAutoPickResponse` /
  `write_rail_selection` no longer re-exported)

## Verification

After code: cleanse related dead paths → `./scripts/verify_finally.sh` → fix
until green (Critical Rule 6).

---

## Exit criteria

- [x] Submit without `--rail` can bind a catalog rail via LLM when confidence
      clears the threshold
- [x] External home/workspace rails appear in the prompt without code changes
- [x] Low confidence / failure degrades to deterministic cascade
- [x] Explicit `--rail` never calls the picker (source=`explicit`; no LLM)
- [x] RFC-231 §10 / RFC-228 / this IG / design draft cross-links consistent
- [x] `verify_finally.sh` green
