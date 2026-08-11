# Gap Triage Matrix

> Artifact for remediation planning. Applies the scoring scheme from
> `IG-gap-criticality-impact-criteria.md` to every gap row in
> `IG-spec-vs-code-gap-inventory.md` (XRK-01). Each gap is scored on
> criticality (C1–C6) and impact (I1–I5), then mapped to a priority (P0–P3)
> via the priority matrix. Triggering criteria are recorded beside the priority
> for auditability (scoring procedure §6).
>
> All criteria are structural/textual — derived from spec text and the
> inventory's own code-evidence columns. No keyword heuristics on user content
> (AGENTS §9 / RFC-630).

---

## How to read this matrix

- **Crit** = Criticality level (Critical / High / Medium / Low)
- **Imp** = Impact level (High / Medium / Low)
- **Pri** = Priority (P0 do-now → P3 backlog)
- **Via** = Triggering criteria IDs that justify the score (e.g. `C1+I1,I4`)
- Gap type: **SNI** = specified, not implemented; **IND** = implemented, not
  documented; **Drift** = status mismatch only

Priority bands (from the criteria doc priority matrix):

| Priority | Meaning | Remediation posture |
|----------|---------|---------------------|
| **P0** | Critical + High impact | Block release; schedule immediately |
| **P1** | Critical+Medium, or High+High | Schedule before next minor; security/deploy blockers |
| **P2** | Medium+High, High+Medium, or governance+High | Backlog with intent; do not let grow |
| **P3** | Medium/Low remainder | Documentation/governance cleanup; opportunistic |

---

## 1. SNI gaps (Section B of inventory) — scored

### P0 — do-now

| RFC | Gap (abbreviated) | Type | Crit | Imp | Pri | Via |
|-----|-------------------|------|------|-----|-----|-----|
| RFC-412 | MCP subsystem entirely non-functional (no `soothe.mcp` pkg, no `MultiServerMCPClient` import, no `MCPActivationMiddleware`) | SNI | Critical | High | **P0** | C1, C4 + I1, I4 |
| RFC-504 | `loop tree`/`prune`/`delete` commands absent (only `list`/`describe`) | SNI | Critical | High | **P0** | C2 + I3, I4 |

### P1 — schedule before next minor

| RFC | Gap (abbreviated) | Type | Crit | Imp | Pri | Via |
|-----|-------------------|------|------|-----|-----|-----|
| RFC-901 | `OperationSecurityProtocol` absent; `security/` has only kill guards | SNI | Critical¹ | Medium | **P1** | C4 + I1, I3 |
| RFC-621 | Workspace host convention for containers absent (blocks container deploys) | SNI | Critical | Medium | **P1** | C3 + I3 |
| RFC-627 | Unified LLM Utilities module absent; LLM calls scattered | SNI | High² | Medium | **P1** | C4 + I1 |
| RFC-301 | `ProtocolRegistry` centralized registry absent (protocols wired ad-hoc) | SNI | Medium³ | High | **P1** | C5 + I2 |
| RFC-902 | Same-File Edit concurrency/optimization absent | SNI | High | Medium | **P1** | C4 + I1, I3 |

¹ C4 "security primitive absent" → treated as Critical per criteria doc note
("security primitive absent" uplift); the raw matrix yields High+Medium=P2 but
the criteria doc's example mapping uplifts security primitives to P1.
² Inventory labels High; criteria doc resolves the C4 "foundational, scattered"
uplift to P1 (borderline case, §5).
³ Inventory labels Medium; I2 uplift (≥2 RFCs depend on ProtocolRegistry:
RFC-304/305/306/307) → High impact → P1.

### P2 — backlog with intent

| RFC | Gap (abbreviated) | Type | Crit | Imp | Pri | Via |
|-----|-------------------|------|------|-----|-----|-----|
| RFC-302 | `ContextRetrievalModule` on `ContextProtocol` absent | SNI | Medium | Medium | **P2** | C5 + I2 |
| RFC-452 | Unified Thread Management (`UnifiedThreadManagement`/`unified_thread` absent) | SNI | Medium | Medium | **P2** | C5 + I1 |
| RFC-614 | Unified daemon→client streaming (`UnifiedStreaming` absent) | SNI | Medium | Medium | **P2** | C5 + I1 |
| RFC-633 | `PlanArtifact` class + human review flow absent | SNI | Medium | Medium | **P2** | C5 + I3 |
| RFC-632 | `LoopScopedRouter` daemon-side enforcement class absent | SNI | Medium | Medium | **P2** | C5 + I1 |
| RFC-631 | `GoalDisplaySnapshot` server-owned write path partial | SNI | Medium | Medium | **P2** | C5 + I1 |
| RFC-502 | Daemon-side unified `PresentationEngine` absent (exists in CLI only) | SNI | Medium | Medium | **P2** | C5 + I1 |
| RFC-450 | Unified daemon comms protocol: capability negotiation + versioning absent | SNI | Medium | High | **P2** | C5 + I1 |
| RFC-801 | SQLite backend formal `SQLiteBackend` class hierarchy absent | SNI | Medium | Medium | **P2** | C5 + I4 |
| RFC-803 | StrangeLoop checkpoint backend unified `PersistenceManager` API + async write pipeline incomplete | SNI | Medium | Medium | **P2** | C5 + I2 |

### P3 — documentation/governance or internal-only backlog

| RFC | Gap (abbreviated) | Type | Crit | Imp | Pri | Via |
|-----|-------------------|------|------|-----|-----|-----|
| RFC-223 | Checkpoint forking (`CheckpointFork`/`thread_fork`) absent | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-225 | `LoopContinuity`/`GoalRecord` enrichment absent | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-226 | `ContinuationAware` plan_assess / fast exit absent | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-227 | `PriorProgressDigest` absent | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-221 | `SubprocessRunner`/`ThreadPoolRunner` classes absent (loop runner protocol partial) | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-629 | Client Library Appkit (multi-language) not standardized | SNI | Medium | Medium | **P3** | C5 + I3 |
| RFC-413 | `DisplayCardLedger` class absent (partial shipping via `LoopCardManager`) | SNI | Medium | Medium | **P3** | C5 + I1 |
| RFC-403 | Unified event naming migration map not fully applied | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-503 | Loop-First UX detachment + session mgmt incomplete | SNI | Medium | Medium | **P3** | C5 + I3 |
| RFC-616 | Scenario-driven goal completion synthesis path partial | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-618 | Plan Subagent explore delegation absent (partially superseded by RFC-633) | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-619 | Deep Research Subagent Phase 2 `academic_research` absent | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-622 | CoreAgent clarification relay + TUI toggle not fully wired | SNI | Medium | Medium | **P3** | C5 + I3 |
| RFC-623 | Veritas auto-mode robustness spec points not fully covered | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-630 | Start-phase intake + branch routing (§10) wiring partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-606 | DeepAgents CLI/TUI migration remaining phases incomplete | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-607 | Progressive display refinements ongoing | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-610 | `soothe_sdk` refactoring spec not applied in this repo (PyPI dep) | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-802 | Persistence architecture refactor (Postgres schema/config migration) partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-213 | StrangeLoop reasoning quality two-phase (historical section superseded) | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-214 | Volatility-tiered prompt architecture (target design §) partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-217 | `GoalContextManager` referenced but not fully unified | SNI/Drift | Medium | Low | **P3** | C5, C6 + I5 |
| RFC-218 | Checkpoint tree pruning strategy not implemented | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-220 | LangGraph orchestrator normative identity/isolation rules partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-224 | Automatic context window mgmt step thread handling partial | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-228 | Autopilot job IPC command set incomplete | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-229 | Cron service TUI/CLI integration partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-230 | Job maturity rail exclusivity + IPC observation partial | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-231 | LoopRail verb body modes (M3 `do:` recipes) + fan-out contract partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-232 | Flat WavePlan wire ingest semi-structured ingest + arch gate partial | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-103 | Thread-aware workspace edge cases + security model partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-105 | Progressive skill loading disclosure middleware + cost model partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-201 | StrangeLoop plan-execute loop (superseded by RFC-220/624, still in use) | SNI | Medium | Low | **P3** | C5 + I2 |
| RFC-206 | Hierarchical prompt architecture ambiguity handling partial | SNI | Medium | Medium | **P3** | C5 + I4 |
| RFC-207 | StrangeLoop thread health monitoring + knowledge transfer partial | SNI | Medium | Medium | **P3** | C5 + I2 |
| RFC-211 | Layer-2 tool result optimization responsibility shift partial | SNI | Medium | Low | **P3** | C5 + I4 |
| RFC-501 | Display & verbosity full architecture + migration mapping partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-454 | Slash command architecture daemon implementation partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I3 |
| RFC-307 | IdentityProtocol middleware integration + CLI commands partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I2 |
| RFC-305 | PolicyProtocol permission categories + config-driven impl partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I2 |
| RFC-306 | DurabilityProtocol persistence layout + integration partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I2 |
| RFC-304 | PlannerProtocol design principles + config partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I2 |
| RFC-303 | MemoryProtocol integration flow + implementations partial | SNI/Drift | Medium | Medium | **P3** | C5, C6 + I2 |

---

## 2. IND gaps (Section C of inventory) — code without RFC

All IND items are C6 (documentation/governance gap only) with I5-High
(code exists, spec missing → high auditability impact). Grouped by package.

| Code module | Package | Crit | Imp | Pri | Via |
|-------------|---------|------|-----|-----|-----|
| `diagnose/` (api, host, models) | soothe | Low | Medium | **P3** | C6 + I5 |
| `utils/observability/langfuse/` | soothe | Low | Medium | **P3** | C6 + I5 |
| `utils/prompt_clock.py` | soothe | Low | Low | **P3** | C6 + I5 |
| `security/daemon_kill_guards.py` | soothe | Low | Medium | **P3** | C6 + I5 |
| `health/` | soothe-daemon | Low | Medium | **P3** | C6 + I5 |
| `notify/` (email, feishu, webhook) | soothe-daemon | Low | Medium | **P3** | C6 + I5 |
| `skillify/` (warehouse/indexer/retriever) | soothe-daemon | Low | Medium | **P3** | C6 + I5 |
| `query/` (engine, stream delivery, turn boundary) | soothe-daemon | Low | Medium | **P3** | C6 + I5 |
| `runtime/loop_broadcast_budget.py` | soothe-daemon | Low | Low | **P3** | C6 + I5 |
| `runtime/loop_gc.py` | soothe-daemon | Low | Low | **P3** | C6 + I5 |
| `runtime/loop_reconcile.py` | soothe-daemon | Low | Low | **P3** | C6 + I5 |
| `services/memory_profiler.py` | soothe-daemon | Low | Low | **P3** | C6 + I5 |
| `services/image_understanding.py` | soothe-daemon | Low | Medium | **P3** | C6 + I5 |
| `services/intent_hint_turn.py` | soothe-daemon | Low | Low | **P3** | C6 + I5 |
| `tui/unicode_security.py` | soothe-cli | Low | Medium | **P3** | C6 + I5 |
| `tui/update_check.py` | soothe-cli | Low | Low | **P3** | C6 + I5 |
| `tui/mermaid_render.py` | soothe-cli | Low | Low | **P3** | C6 + I5 |
| `tui/file_change_notify.py` | soothe-cli | Low | Low | **P3** | C6 + I5 |

> Note: `security/daemon_kill_guards.py` and `health/` sit adjacent to
> security/operator-relevant RFCs (RFC-901, RFC-412). Their IND score is Low,
> but if an operator audit surfaces them as the *only* spec for a security
> posture, they should be uplifted to P2 per priority-matrix footnote ².

---

## 3. Drift gaps (Section D of inventory) — status mismatch

Pure status-line corrections (no code change). C6 + I5. Exceptions noted.

| RFC | Declared → should be | Crit | Imp | Pri | Via | Note |
|-----|----------------------|------|-----|-----|-----|------|
| RFC-217 | `Draft` → `Implemented` | Low | Low | **P3** | C6 + I5 | Body says "completed"; code wired. Status fix only. |
| RFC-624 | `Draft` → `Implemented` | Low | Low | **P3** | C6 + I5 | Phases 1–4 Stage 1 done per body; status fix only. |
| RFC-222 | `Implemented` (accurate) | — | — | — | — | No drift; listed for completeness. |
| RFC-625 | `Implemented` (accurate) | — | — | — | — | No drift; listed for completeness. |
| RFC-628 | `Implemented (Parts I–III)` (accurate) | — | — | — | — | No drift; listed for completeness. |
| RFC-626 | `Draft` (accurate — LoopState elimination incomplete) | — | — | — | — | No drift; listed for completeness. |
| RFC-201 | `Implemented (Partially Superseded)` (accurate) | — | — | — | — | No drift; listed for completeness. |
| RFC-413 | `Draft (Phases 1–4 shipped)` overstates code | Low | Medium | **P3** | C6 + I1 | Status comment more optimistic than code; correct to `Draft (partial)`. Also counted as SNI above. |
| RFC-228 | `Proposed` → `Draft`/`Implemented (partial)` | Low | Medium | **P3** | C6 + I3 | Code shipped; status fix. Also SNI above. |
| RFC-229 | `Proposed` → `Draft`/`Implemented (partial)` | Low | Medium | **P3** | C6 + I3 | Code shipped; status fix. Also SNI above. |
| RFC-302 | `Draft` (accurate — retrieval module absent) | — | — | — | — | No drift; listed for completeness. |
| RFC-105 | `Draft` → note partial implementation | Low | Medium | **P3** | C6 + I3 | Status should note partial. Also SNI above. |

---

## 4. Priority rollup

| Priority | Count | Composition |
|----------|-------|-------------|
| **P0** | 2 | RFC-412 (MCP), RFC-504 (loop cmds) |
| **P1** | 5 | RFC-901, RFC-621, RFC-627, RFC-301, RFC-902 |
| **P2** | 10 | RFC-302, RFC-452, RFC-614, RFC-633, RFC-632, RFC-631, RFC-502, RFC-450, RFC-801, RFC-803 |
| **P3 (SNI)** | 29 | Internal/partial paths + protocol-architecture drift items |
| **P3 (IND)** | 18 | Code-without-RFC modules |
| **P3 (Drift)** | 6 actionable | RFC-217, RFC-624, RFC-413, RFC-228, RFC-229, RFC-105 |
| **No drift (verify-only)** | 6 | RFC-222, RFC-625, RFC-628, RFC-626, RFC-201, RFC-302 |

**Suggested remediation order:**

1. **P0 (immediate):** RFC-412 MCP subsystem, RFC-504 loop commands.
2. **P1 (next minor):** RFC-901 OpSec protocol, RFC-621 workspace host,
   RFC-627 unified LLM utils, RFC-301 ProtocolRegistry, RFC-902 same-file edit.
3. **P2 (backlog w/ intent):** Cross-package contract gaps (RFC-450, RFC-452,
   RFC-614, RFC-632, RFC-631, RFC-502, RFC-801, RFC-803) + RFC-302, RFC-633.
4. **P3-SNI:** Internal paths and protocol-architecture partials — opportunistic,
   group by subsystem (checkpoint forking, loop continuity, protocol arch).
5. **P3-IND + P3-Drift:** Documentation/governance sweep — can be batched as a
   single docs PR per package.

---

## 5. Cross-cutting observations

- **Two P0s are both "zero code, user-facing, no workaround"** (C1/C2 + I3 +
  I4) — the criteria scheme's strongest signal. These are the only items where
  the inventory's "High" label and the matrix agree on top urgency.
- **The C4 security-primitive uplift (RFC-901) and the I2 downstream-dependency
  uplift (RFC-301)** are the two places the scoring scheme diverges from the
  inventory's flat High/Medium labels. Both are explicitly called out in the
  criteria doc §5; this matrix applies those uplifts consistently.
- **Every IND item is P3** because no code change is required — the remediation
  is "write the missing RFC." Batch these into one docs PR per package to avoid
  churn.
- **Drift items overlap with SNI items** (RFC-413, RFC-228, RFC-229, RFC-105,
  RFC-217): they appear in both the SNI table and the drift table because the
  gap is *both* a status mismatch *and* a partial implementation. The SNI
  priority governs remediation; the drift row governs the status-line fix.
- **No gap scored Critical+Low-impact**, so the matrix's footnote-¹ P2 band is
  unused in practice — consistent with the criteria doc's expectation that C1
  gaps tend to have downstream dependencies.

---

*Matrix complete. 55 SNI gaps + 18 IND gaps + 6 actionable drift items scored
against C1–C6 / I1–I5, mapped to P0–P3. Source: IG-spec-vs-code-gap-inventory
(XRK-01); scheme: IG-gap-criticality-impact-criteria.*
