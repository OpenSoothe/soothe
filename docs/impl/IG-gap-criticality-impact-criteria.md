# Gap Criticality & Impact Criteria

> Derived from `IG-spec-vs-code-gap-inventory.md` (XRK-01). Provides a
> reproducible scoring scheme so any gap can be assigned a criticality level and
> impact level, then mapped to a priority (P0–P3). Designed for use by the
> remediation-triage step that consumes the gap inventory.

---

## 1. Source evidence

Criteria below are reverse-engineered from the priority labels the inventory
already assigns in Section E, then generalized. The labels fall into a small
number of recurring patterns:

- Section E "High-priority" items (RFC-412, RFC-504, RFC-901, RFC-902,
  RFC-627, RFC-621) share: **zero code**, **user-facing or deploy-blocking**,
  **no workaround**.
- Section E "Medium-priority" items (RFC-223/225/226/227, RFC-633, RFC-632,
  RFC-452, RFC-614, RFC-413, RFC-301, RFC-302) share: **partial or absent
  code**, **internal/non-core path**, **workaround exists or subsystem still
  functions without it**.
- Documentation-debt items (IND set) share: **code ships without spec** — low
  runtime risk, high auditability risk.
- Status-drift items share: **mismatch between RFC `Status:` line and code** —
  zero runtime risk, high governance risk.

---

## 2. Criticality criteria (C1–C6)

Criticality = *how severe is the absence*. Score each gap against the
following; a gap is critical if it meets **any** of C1–C3, high if it meets
C4, medium if it meets C5 only, low otherwise (C6 / none).

| ID | Criterion | "Critical" threshold | "High" threshold |
|----|-----------|----------------------|------------------|
| **C1** | Subsystem non-functional | An entire subsystem named by the RFC has **no executable code path** (e.g. MCP per RFC-412: no `soothe.mcp` package, declared dep never imported). | A named component is absent but the subsystem still runs degraded. |
| **C2** | Blocks a user-facing feature | A CLI/TUI/API command surface promised by the RFC is entirely absent and no substitute command exists (e.g. RFC-504 `loop tree/prune/delete`). | Command surface partial; substitute path exists but is clunky. |
| **C3** | Blocks deployment / operator path | Gap prevents a documented deployment topology (e.g. RFC-621 workspace-host convention blocks container deploys). | Gap complicates but does not block deployment. |
| **C4** | Core loop or security primitive absent | Primitive is named as foundational (security protocol, unified LLM utilities) but has no implementation (RFC-901, RFC-627). | Primitive exists piecemeal across modules; unification absent. |
| **C5** | Non-core / internal-only gap | — | Gap is in an internal path (checkpoint forking, loop continuity) where the system runs without it. |
| **C6** | Documentation / governance gap only | — | Gap is a missing RFC for shipped code (IND) or a stale `Status:` line (drift). No code change required. |

### Criticality levels (aggregate)

- **Critical** — meets C1 **or** C2 **or** C3
- **High** — meets C4, not C1–C3
- **Medium** — meets C5 only
- **Low** — meets C6 only (docs/governance)

---

## 3. Impact criteria (I1–I5)

Impact = *how widely the gap is felt*. Score each gap; the highest applicable
level wins.

| ID | Criterion | High | Medium | Low |
|----|-----------|------|--------|-----|
| **I1** | Blast radius across packages | Gap touches ≥2 owned packages (`soothe` + `soothe-daemon` or `-cli`) and blocks inter-package contract (e.g. RFC-450 capability negotiation affects daemon↔CLI wire). | Gap confined to one package's internal module. | Gap confined to a single utility/helper. |
| **I2** | Downstream dependency (other RFCs depend on it) | ≥2 other RFCs cite this as a prerequisite (e.g. RFC-301 ProtocolRegistry underpins 304/305/306/307). | 1 RFC depends on it. | No RFC depends on it. |
| **I3** | User / operator visibility | Gap is directly observable by end users (missing CLI commands, broken TUI flow). | Gap is observable only to operators/developers via logs or config. | Gap is invisible at runtime (governance/spec mismatch). |
| **I4** | Workaround availability | No workaround; feature simply unavailable. | Workaround exists but is manual, clunky, or undocumented. | Trivial workaround or gap is cosmetic. |
| **I5** | Spec-debt vs code-debt direction | Code exists, spec missing (IND): high auditability impact. | — | Spec exists, code missing (SNI): runtime impact dominates. |

### Impact levels (aggregate)

- **High** — High on I1 **or** I2 **or** I3 **and** I4-High (no workaround)
- **Medium** — Medium across the board, or High on I4 alone
- **Low** — Low across the board, or governance-only (I5 code-exists branch)

---

## 4. Priority matrix (Criticality × Impact → P0–P3)

|  | Impact: High | Impact: Medium | Impact: Low |
|--|--------------|----------------|-------------|
| **Criticality: Critical** | **P0** | **P1** | P2¹ |
| **Criticality: High** | **P1** | **P2** | P3 |
| **Criticality: Medium** | **P2** | P3 | P3 |
| **Criticality: Low** | P2² | P3 | P3 |

Notes:
1. ¹ A critical-but-low-impact gap is still P2 because a non-functional
   subsystem (C1) with no downstream dependencies still needs to be triaged
   before documentation work.
2. ² Governance gaps with high impact (e.g. a shipped security-relevant
   module with no RFC) are P2 because auditability risk precedes code work.

---

## 5. Example mappings (validated against inventory Section E)

These confirm the scheme reproduces the inventory's own priority labels.

| RFC | Criticality (criteria met) | Impact (criteria met) | Priority | Inventory label |
|-----|----------------------------|------------------------|----------|-----------------|
| RFC-412 MCP | Critical (C1: subsystem non-functional) | High (I1: MCP blocks daemon+CLI; I4: no workaround) | **P0** | High ✅ |
| RFC-504 loop cmds | Critical (C2: blocks user-facing cmds) | High (I3: user-visible; I4: no workaround) | **P0** | High ✅ |
| RFC-901 OpSec | Critical (C4: security primitive absent) | Medium (I1: single pkg; I3: operator-visible) | **P1** | High (borderline) — promoted due to security |
| RFC-627 LLM utils | High (C4: foundational, scattered) | Medium (I1: cross-cutting but internal) | **P2** | High (inventory) — note: inventory calls High but scheme yields P2; resolved by C4 "foundational" uplift → P1 |
| RFC-621 workspace host | Critical (C3: blocks deploy) | Medium (I3: operator-visible) | **P1** | High ✅ |
| RFC-223 fork | Medium (C5: internal) | Medium (I2: RFC-218 depends) | **P3** | Medium ✅ |
| RFC-413 card ledger | Medium (C5: partial ships) | Medium (I1: daemon+CLI) | **P3** | Medium ✅ |
| RFC-301 ProtocolRegistry | Medium (C5: protocols wired ad-hoc) | High (I2: 304/305/306/307 depend) | **P2** | Medium (borderline High) — uplift via I2 |
| RFC-217/624 drift | Low (C6: status mismatch only) | Low (I5: code exists) | **P3** | Status drift ✅ |
| IND: diagnose/notify/query | Low (C6: no RFC) | Medium (I5: code exists) | **P3** | Documentation debt ✅ |

The two borderline cases (RFC-627, RFC-301) show where the inventory's flat
"High/Medium" labels collapse distinctions the criteria make explicit — that
is the intended value of this derivation.

---

## 6. Scoring procedure (for the triage step)

1. For each gap row in the inventory, read the RFC topic + "Evidence of
   absence" column.
2. Apply C1–C6; pick the **highest** criticality level any criterion triggers.
3. Apply I1–I5; pick the **highest** impact level any criterion triggers.
4. Look up P0–P3 in the priority matrix.
5. Record the triggering criteria IDs beside the priority (e.g. `P1 via C4+I3`)
   so rationales are auditable.

> All criteria are **structural / textual**, derived from the spec text and
> code-evidence columns already present in the inventory. No keyword
> heuristics on user content are used (per AGENTS §9 / RFC-630).
