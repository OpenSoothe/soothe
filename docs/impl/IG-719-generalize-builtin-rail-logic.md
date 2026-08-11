# IG-719: Generalize builtin rail logic + review closeout

**Created**: 2026-08-07  
**Status**: Implemented  
**Related**: [RFC-231](../specs/RFC-231-looprail-rail-exec.md),
[RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md),
[IG-700](../archive/impl/IG-700-greenfield-fanout-closeout.md),
[IG-715](IG-715-migration-wave-fanout.md),
[IG-718](IG-718-fanout-slice-terminology.md)

---

## Goal

Make builtin LoopRail **logic** structure-driven (fanout / tags / events) instead
of architecture-tag or project-domain forks, and close the prior review of
rails, engine, verbs, and workflows.

## Design rules

1. **Fan-out mode** = bound rail declared `fanout:` (`fanout_enabled` on
   structural facts), not “any architecture-tagged goal.”
2. **Non-fanout rails** use tag/event short-circuits only.
3. **Domain copy** lives only in that rail’s YAML verb briefs; engine + shared
   defaults stay general.
4. **No keyword heuristics** for content judgment (RFC-630).
5. **Align NL ↔ SC ↔ flow** — unused conditions removed; YAML matches guards.

## Deliverables

- [x] Structural `fanout_enabled` (+ `retry_count`) in interpreter facts
- [x] Guards: fanout_mode gates; `branch_is_stuck` for all rails;
      `architecture_failed` = architecture tag only; integrate-skipped commit;
      `needs_human` / `checker_failed_recoverable` tag SCs; idle events
- [x] Agent-facing WavePlan copy without “host persists”
- [x] Architecture gate: `architecture` tag (not bare `planning`)
- [x] Catalog rejects list `then:`; merge sentinels use `None`
- [x] Builtin YAML versions + idle recovery + dead conditions removed
- [x] README + looprail-creator skill/templates refresh
- [x] Unit tests (rails + related autopilot)

## Non-goals

- Non-coding domain rails
- L0 `do:` for wave makers / feedback
- Wiring `merge_branches` into a builtin flow
- Pinning builtin rail integrity hashes (per-file `integrity_hash` on load remains)
