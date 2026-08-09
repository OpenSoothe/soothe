# IG-736: Autopilot prompts module (`soothe.autopilot.prompts`)

**Created**: 2026-08-09  
**Status**: Implemented  
**Package**: `soothe`  
**Related**: [IG-705](IG-705-autopilot-one-level-layout.md),
[RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md),
[RFC-204](../specs/RFC-204-strange-loop-protocol.md) (report-commit),
StrangeLoop mirror: `soothe.sloop.prompts`

---

## Goal

Extract Autopilot LLM prompt text into a dedicated one-level package
`soothe.autopilot.prompts`, mirroring `soothe.sloop.prompts`: static fragments,
named system roles, thin builders, and reasoners/guards that only invoke.

## Design rules (MUST)

1. **One-level package** — `soothe.autopilot.prompts.*` only (IG-705).
2. **No shims** — delete `verify/verifier_prompts.py`; update all importers.
3. **Instructions vs envelope** — rubrics/JSON schemas/security in fragments;
   per-call facts via builders / `.format` kwargs.
4. **Named roles** — short system role strings in `roles.py` (no inline
   `"You are an expert…"` in reasoners).
5. **Guard injection boundary** — system fragment owns SECURITY RULES;
   user envelope wraps condition/summary in `<untrusted_data>`.
6. **Behavior freeze** — do not change consensus vocab (`accept` / `send_back` /
   `fail`), maturity signals, verifier JSON keys, or guard short-circuit logic.
7. **No IG/RFC ids** in runtime prompt strings visible to models as product
   branding (internal docstrings/comments OK).

## Layout

```text
soothe/autopilot/prompts/
  __init__.py
  roles.py
  envelopes.py
  fragments/          # prefetch at import
    verify/
    consensus/
    maturity/
    rail/
  verify.py
  consensus.py
  maturity.py
  guards.py
```

## Work items

- [x] Add `autopilot/prompts` package + fragments
- [x] Rewire `verifier_reasoner`, `backoff_reasoner`, `consensus`,
      `job_maturity`, `rail.guards`
- [x] Delete `verify/verifier_prompts.py`
- [x] Update unit tests (consensus, verifier prompts)
- [x] `./scripts/verify_finally.sh`

## Non-goals

- Changing decision schemas or structured-output models
- Moving CE projection helpers (`report_projection`, `dag_ops`) into prompts
- Putting Autopilot prompts under `soothe.prompts` (systemwide)

## Cleanse (post-impl)

- [x] Slim `prompts/__init__` to builders + roles + render/format helpers
      (raw templates via `prompts.fragments` / `prompts.verify`)
- [x] Sync active docs: RFC-625 trees, wiki CE absorb path, IG-705 layout
- [x] Leave `docs/archive/**` historical paths untouched

## Verification

- Existing consensus / verifier prompt format tests pass under new imports
- Guard evaluator still fail-closed; structural short-circuit unchanged
- Full `./scripts/verify_finally.sh` green
