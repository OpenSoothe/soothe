# IG-707: Autopilot automatic consensus (no operator suspend)

**Created**: 2026-08-06  
**Status**: Done  
**Related**: [RFC-204](../specs/RFC-204-autopilot-mode.md),
[IG-680](IG-680-autopilot-dag-health-evidence-deps.md),
[IG-690](IG-690-consensus-pass-full-evidence.md),
[IG-691](IG-691-integrate-thrash-rail-tag-loss.md),
[IG-693](IG-693-rail-subgoal-consensus-exhaustion-recovery.md),
[IG-697](IG-697-engine-deadlock-recovery.md),
[IG-710](IG-710-consensus-trust-sloop-response.md)

---

## Goal

Autopilot is a fully automatic procedure. Single-goal completion must never
park waiting for an operator. Consensus and related host paths choose only
**accept**, **send_back** (retry with guidance), or **fail** (host recovery:
monitor backoff, LoopRail, engine health).

`suspend` / `awaiting_clarification` remain for explicit job-level pauses
(`pause_job`, rail `pause_for_user` after Veritas defer/deny — see
[IG-737](IG-737-rail-pause-veritas.md)) and interactive (non-autopilot) loops —
not for completion judgment.

---

## Design rules

1. Consensus structured verdict: `accept | send_back | fail` (drop `suspend`).
2. Consensus judge input is goal text + StrangeLoop response (IG-710); no host
   workspace evidence-grounding gate. Judge may `send_back` on thin response;
   budget exhaust → fail.
3. Consensus LLM / missing model → `fail` (not suspend).
4. Send-back budget exhaust → **always** `fail` (unify non-rail with IG-693 rail).
5. Worker `needs_replan` → `send_back` / fail on exhaust (not suspend).
6. Crash-recovery budget exhaust → `fail` (not suspend).
7. Health prompts: do not teach “operator resume” for consensus exhaustion.

---

## Out of scope

- Clarification TUI / interactive `awaiting_clarification` for human loops.
- Explicit operator `pause_job` API.
- Rail `pause_for_user` Veritas auto-clarify (delivered in
  [IG-737](IG-737-rail-pause-veritas.md); suspend remains for defer/deny).
- Implementing `max_defer_age_hours` sweeper (unused config; separate IG if needed).

---

## Deliverables

- [x] `consensus.py` — `fail` replaces `suspend` in schema + prompt
- [x] `AutopilotService._apply_consensus_and_finalize` — automatic paths only
- [x] `needs_replan` handling → send_back / fail
- [x] `ContextEngine.send_back_goal` — always fail on exhaust
- [x] `ContextEngine.recover` — fail when crash budget exhausted
- [x] RFC-204 + verifier prompts + tests
- [x] `./scripts/verify_finally.sh` green

---

## Test plan

- Consensus prompt / structured verdict tests use `fail` not `suspend`
- Thin/empty sloop response → judge may send_back (pending) or fail on exhaust; never suspended
- No workspace-marker / pytest grounding required before consensus runs (IG-710)
- Non-rail send_back exhaust → failed
- Crash recover over budget → failed
- Health still skips legacy suspended+send_back-exhausted; ordinary suspend OK
