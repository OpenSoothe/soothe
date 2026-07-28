# IG-646 Deprecation Tracking — L1f / L1g / L4

> Tracking doc for the deprecation cycles of legacy shims catalogued in
> [IG-646](IG-646-legacy-shim-decommission-backlog.md). This document records
> the **start** of the D1/D6 wire-protocol deprecation cycle (L1f/L1g) and the
> **2-release-cycle time gate window** for the C1 config migration shim (L4).
>
> It is a tracking instrument, not a spec: it records *when* each cycle started,
> *what* the decommission criterion is, and *when* the criterion may be
> evaluated. Code removal itself stays governed by IG-646 and the relevant RFCs.

---

## Reference Baseline

| Field | Value |
|---|---|
| Catalog | [IG-646 — Legacy Shim Decommission Backlog](IG-646-legacy-shim-decommission-backlog.md) |
| Tracking doc ID | L1f / L1g / L4 (this document) |
| Cycle start date | 2026-07-28 |
| Latest release at start | v0.9.6 (2026-07-25) |
| Release cadence reference | `CHANGELOG.md` (semver; v0.9.x minor line) |
| Total shim sites (catalog) | 47 (8 nano, 14 CLI, 25 daemon) |

---

## L1f — D1: Legacy streaming frame → protocol-1 `next` translator

> **Cycle type:** Wire-protocol deprecation (Priority 1, High Risk, Coordinated RFC).
> Source of record: IG-646 §D1 and §Decommission Priorities → P1.

| Field | Value |
|---|---|
| Shim ID | D1 |
| Package | `soothe-daemon` |
| Location | `packages/soothe-daemon/src/soothe_daemon/server/session.py:39,95,115,145,676,693,705` |
| Symbol | `_wrap_legacy_streaming_frame()`, `_translate_legacy_frame()` |
| Type | Wire migration (protocol-0 → protocol-1) |
| Risk | **High** |
| Behavior | Wraps legacy streaming frames as protocol-1 `next` envelopes for clients still using protocol-0. Active protocol translation. |
| Decommission criterion | All clients have migrated to protocol-1 wire format. Requires client version audit + deprecation cycle. |
| Priority group | P1 — Wire Protocol Migration (with D2, D3, D4, D5, D6, D10, D11, D17) |

### Deprecation cycle (4-release, coordinated RFC)

Per IG-646 §Decommission Priorities → P1, D1 is decommissioned as part of a
single coordinated RFC spanning four releases:

| Step | Release | Action | Status |
|---|---|---|---|
| 1 | **N** (announce) | Announce protocol-0 deprecation in release notes + migration guide | **Cycle start — 2026-07-28** (pending: identify release N; next minor after v0.9.6) |
| 2 | N+1 | Emit deprecation warnings when protocol-0 messages are received | Pending N |
| 3 | N+2 | Reject protocol-0 messages at the protocol layer | Pending N+1 |
| 4 | N+3 | Remove D1 translation shims (and all P1 shims) | Pending N+2 |

### Exit gate (D1-specific)

Before removal at release N+3, the following must be verified:

- [ ] Client version audit confirms zero deployed clients still send protocol-0
      streaming frames.
- [ ] `server/session.py` translation call sites (lines 39, 95, 115, 145, 676,
      693, 705) are no longer triggered in production traffic for ≥1 full release.
- [ ] Telemetry/log counters on the legacy-frame path read zero for the full
      N+2 → N+3 window.

**Do not remove D1 until this gate passes.** Removing before the criterion is
met will break live wire-protocol clients.

---

## L1g — D6: Legacy flat-form validation exemption

> **Cycle type:** Wire-protocol deprecation (Priority 1, Medium Risk, Coordinated RFC).
> Source of record: IG-646 §D6 and §Decommission Priorities → P1.
> D6 is coupled to D1/D2/D3 via the same protocol-0→1 migration: it exempts
> legacy flat-form messages from strict validation during the migration window.

| Field | Value |
|---|---|
| Shim ID | D6 |
| Package | `soothe-daemon` |
| Location | `packages/soothe-daemon/src/soothe_daemon/protocol/validation.py:38,53` |
| Symbol | Legacy flat-form exemption during migration window |
| Type | Wire migration |
| Risk | **Medium** |
| Behavior | Exempts legacy flat-form messages from strict validation during the protocol-0→1 migration window. |
| Decommission criterion | All clients use protocol-1. Remove exemption when flat-form is rejected at dispatch. |
| Priority group | P1 — Wire Protocol Migration (with D1, D2, D3, D4, D5, D10, D11, D17) |

### Deprecation cycle (4-release, coordinated RFC)

D6 rides the **same** coordinated RFC cycle as D1 (§Decommission Priorities →
P1). The steps are shared, not independent:

| Step | Release | Action (shared with D1/D2/D3 P1 cohort) | Status |
|---|---|---|---|
| 1 | **N** (announce) | Announce protocol-0 deprecation | **Cycle start — 2026-07-28** (shared with L1f) |
| 2 | N+1 | Emit deprecation warnings on legacy flat-form reception | Pending N |
| 3 | N+2 | Reject flat-form at dispatch (line 558 is already envelope-only) | Pending N+1 |
| 4 | N+3 | Remove D6 validation exemption (and D1/D2/D3 translation shims) | Pending N+2 |

### Exit gate (D6-specific)

D6's criterion is nested on D2/D3's dispatch rejection:

- [ ] Flat-form messages are **rejected at dispatch** (release N+2), not merely
      exempted from validation.
- [ ] `protocol/validation.py:38,53` exemption path is not triggered for ≥1 full
      release after dispatch rejection lands.
- [ ] D1 exit gate (above) is also satisfied — D6 is not removable before D1.

---

## L4 — C1: Legacy CLI config path migration (2-release time gate)

> **Cycle type:** Config migration (Priority 3, Low Risk, Time-Gated).
> Source of record: IG-646 §C1 and §Decommission Priorities → P3.
> Unlike L1f/L1g, L4 is **time-gated**, not audit-gated: the decommission
> criterion is "2 release cycles have elapsed" after the migration guide is
> published.

| Field | Value |
|---|---|
| Shim ID | C1 |
| Package | `soothe-cli` |
| Location | `packages/soothe-cli/src/soothe_cli/tui/model_config.py:23-50` |
| Symbol | `_LEGACY_CLI_CONFIG_PATH` + migration logic |
| Type | Config migration (one-time file rename) |
| Risk | **Low** |
| Behavior | Detects old `config.yml` path and renames to `cli_prefs.yml` on load. |
| Decommission criterion | All users have migrated to `cli_prefs.yml`. Can be removed after 2 release cycles. |
| Priority group | P3 — Config Migration (with N1-N5, C2, C3, C5, D16) |

### 2-release-cycle time gate window

Per IG-646 §Decommission Priorities → P3, the P3 strategy is:

1. Document current config format in migration guide.
2. Wait 2 release cycles.
3. Remove migration guards and aliases.

The time-gate window for C1, anchored at the cycle start:

| Milestone | Release | Target date (approx.) | Status |
|---|---|---|---|
| Migration guide published + cycle clock starts | **N** (= v0.9.6 + 1 minor) | 2026-07-28 (cycle start; guide publication pending) | **Start — 2026-07-28** |
| 1st release cycle elapsed | N+1 | Pending N tag | Pending |
| 2nd release cycle elapsed — **earliest removal window opens** | **N+2** | Pending N+1 tag | Pending |
| Removal window closes (recommended latest) | N+3 | Pending N+2 tag | Pending |

> The **earliest** C1 can be removed is release **N+2** (two full release cycles
> after the migration guide is published at release N). Removal at N+2 requires
> that the `cli_prefs.yml` migration path has not logged a rename event for the
> full N+1 → N+2 window; if any legacy `config.yml` rename is still observed,
> defer removal to N+3 and re-verify.

### Exit gate (C1-specific)

- [ ] Migration guide documenting the `config.yml` → `cli_prefs.yml` rename is
      published at release N.
- [ ] Two full release cycles (N → N+1 → N+2) have elapsed.
- [ ] No legacy `config.yml` rename events logged in the N+1 → N+2 window.
- [ ] `soothe_cli.tui.model_config._LEGACY_CLI_CONFIG_PATH` and the rename
      logic at `model_config.py:23-50` are the only call sites of the legacy
      path (grep-verified before deletion).

---

## Cross-shim coordination notes

1. **L1f ↔ L1g coupling.** D1 and D6 are in the same P1 RFC cohort. D6's exit
   gate ("flat-form rejected at dispatch") is the release-N+2 step of D1's
   cycle. Do not attempt to decommission D6 independently of D1/D2/D3.

2. **L4 is independent of L1f/L1g.** C1 (P3, config) is on a separate, slower,
   time-gated track. Its removal does not block on, and is not blocked by, the
   P1 wire-protocol RFC. Track the two windows separately.

3. **Release numbering.** "Release N" is the first release in which the
   deprecation announcement (P1) or migration guide (P3) ships. As of the cycle
   start (2026-07-28), the latest tagged release is **v0.9.6** (2026-07-25);
   release N has not yet been cut. Update the milestone tables above with
   concrete tags once release N ships.

4. **No code removal in this step.** This document records cycle starts and
   gates only. Code removal is governed by IG-646 and the coordinated P1 RFC;
   do not delete shims until their exit gates pass.

---

## Changelog

| Date | Change |
|---|---|
| 2026-07-28 | Created. Recorded L1f (D1) + L1g (D6) P1 wire-protocol deprecation cycle start and L4 (C1) P3 2-release time-gate window, anchored at v0.9.6 baseline. |
