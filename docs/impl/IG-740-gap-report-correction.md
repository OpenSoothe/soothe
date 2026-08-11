# IG-740: Spec-vs-Code Gap Report Correction

**Created**: 2026-08-11
**Status**: Implemented
**Related**: [Gap Inventory](IG-spec-vs-code-gap-inventory.md), [Triage Matrix](IG-gap-triage-matrix.md)

---

## Goal

Correct the false-positive "SNI — specified, not implemented" classifications
in the gap inventory and triage matrix. Source verification (XRK-02) against
`packages/{soothe, soothe-daemon, soothe-cli}` shows that multiple RFCs flagged
as "absent" are in fact implemented — some with `Status: Implemented` in the
RFC itself. The correction re-places each affected RFC at its true priority.

## Method

For every gap row in `IG-spec-vs-code-gap-inventory.md` §B, the primary
class/module/function named in the spec was searched (literal grep) across
`packages/` source. When a hit was found, the file was read to confirm the
symbol is a real implementation (not a string literal or docstring mention).

## A. False positives — implemented, misclassified as SNI

These RFCs are **already implemented** and should be removed from the SNI gap
inventory. Their RFC `Status:` line agrees.

| RFC | Inventory claim | Actual state (verified) | Source location |
|-----|-----------------|--------------------------|-----------------|
| RFC-412 | MCP "entirely non-functional"; no `soothe.mcp` pkg | `soothe.mcp` package exists; `ProgressiveMCPRegistry`, `MCPToolDescriptor`, `merge_mcp_activation` (LangGraph reducer) present; `MCPRegistry` wired in daemon `server/core.py` and runner `_thread_manager.py` (full init/cleanup lifecycle per thread) | `packages/soothe/src/soothe/mcp/`; `packages/soothe-daemon/src/soothe_daemon/server/core.py` |
| RFC-504 | `loop tree`/`prune`/`delete` absent | All three implemented in `loop_cmd.py` with full RPC plumbing (10 subcommands: `list`, `show`, `tree`, `prune`, `delete`, `continue`, `resume`, `detach`, `attach`, `new`) | `packages/soothe-cli/src/soothe_cli/cli/commands/loop_cmd.py` |
| RFC-901 | `OperationSecurityProtocol` absent; `security/` only has kill guards | Protocol + `OperationSecurityRequest/Context/Decision` in `protocols/operation_security.py`; `WorkspaceToolOperationSecurity` reference impl with destructive-command deny set + filesystem boundary checks in `security/operation_security.py` | `packages/soothe/src/soothe/protocols/operation_security.py`, `packages/soothe/src/soothe/security/operation_security.py` |
| RFC-627 | Unified LLM Utilities module absent; LLM calls scattered | RFC `Status: Implemented` — `LLMFactory` and `utils/llm` modules live in `soothe_nano.utils.llm` (per package DAG: coding-layer belongs in soothe-nano). `soothe` re-exports via `config.settings.llm_factory`. | `packages/soothe/src/soothe/config/settings.py`; RFC-627 §Status |
| RFC-302 | `ContextRetrievalModule` absent | `ContextRetrievalModule` present in `soothe.context.retrieval` with keyword/embedding/hybrid algorithm versions | `packages/soothe/src/soothe/context/retrieval.py` |
| RFC-502 | Daemon-side `PresentationEngine` absent (CLI only) | `DaemonPresentationEngine` present with reason compression + tool-result summarization | `packages/soothe-daemon/src/soothe_daemon/display/presentation_engine.py` |
| RFC-633 | `PlanArtifact` class + human review absent | `PlanArtifact` BaseModel present with markdown frontmatter parsing + lifecycle status | `packages/soothe/src/soothe/sloop/plans/artifact.py` |
| RFC-631 | `GoalDisplaySnapshot` server-owned write path partial | `GoalDisplaySnapshot` present in `soothe_sdk.display.snapshot_types`; used by daemon `loop_card_manager.py` | `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py` |
| RFC-632 | `LoopScopedRouter` daemon-side enforcement absent | RFC `Status: Implemented` — `router_profile` field wired across daemon `protocol/router.py`, `protocol/schemas.py`, `query/engine.py`, `runner/pool_runner.py`, `runner/ray_actor.py`, `runner/thread_runner.py`, `server/handlers.py`; `LoopRunRequest.router_profile` carries the overlay | `packages/soothe-daemon/src/soothe_daemon/` (7 files); `packages/soothe/src/soothe/protocols/runner.py:85` |
| RFC-413 | `DisplayCardLedger` class absent (partial via `LoopCardManager`) | `LoopCardLedger` present in daemon display; structural live path shipped | `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py` |
| RFC-803 | `PersistenceManager` API + async pipeline incomplete | `StrangeLoopCheckpointPersistenceManager` present with backend-agnostic delegation (PostgreSQL/SQLite), `for_shared_checkpoint_pool` classmethod, shared pool lifecycle | `packages/soothe/src/soothe/sloop/checkpoints/manager.py` |
| RFC-301 | `ProtocolRegistry` centralized registry absent | RFC-301 does **not** specify a `ProtocolRegistry` class — it defines protocol *interface contracts* (`PlannerProtocol`, `PolicyProtocol`, `DurabilityProtocol`, `VectorStoreProtocol`), all present as `@runtime_checkable` Protocols in `packages/soothe/src/soothe/protocols/` | `packages/soothe/src/soothe/protocols/{loop_planner,loop_working_memory,operation_security,runner}.py`; RFC-301 §1, §2 |

## B. Verified genuine gaps (remain SNI)

These survived source verification — no implementation found in
`packages/` for the named component.

| RFC | Specified component | Verification | Priority (corrected) |
|-----|---------------------|--------------|----------------------|
| RFC-902 | `SameFileEdit` concurrency/optimization | Zero hits for `SameFileEdit`/`same_file_edit`/`edit_lock` across `packages/` | **P1** (unchanged) |
| RFC-621 | `WorkspaceHost` container host convention | Zero hits for `WorkspaceHost`/`workspace_host` | **P1** (unchanged) |
| RFC-452 | `UnifiedThreadManagement` | Zero hits | **P2** (unchanged) |
| RFC-614 | `UnifiedStreaming` framework | Zero hits | **P2** (unchanged) |
| RFC-223 | `CheckpointFork`/`thread_fork` | Zero hits | P3 (unchanged) |
| RFC-225 | `LoopContinuity`/`GoalRecord` | Zero hits | P3 (unchanged) |
| RFC-226 | `ContinuationAware` | Zero hits | P3 (unchanged) |
| RFC-227 | `PriorProgressDigest` | Zero hits | P3 (unchanged) |
| RFC-221 | `SubprocessRunner`/`ThreadPoolRunner` | Zero hits (only `ray_runner.py`/`ray_actor.py`) | P3 (unchanged) |
| RFC-629 | Client Appkit multi-language API | Not standardized across `client/{go,python,rust,typescript}` submodules | P3 (unchanged) |
| RFC-403 | Event naming migration map | Migration not fully applied | P3 (unchanged) |
| RFC-503 | Loop-First UX detachment + session mgmt | Partial | P3 (unchanged) |
| RFC-616 | Scenario-driven synthesis | Partial | P3 (unchanged) |
| RFC-618 | Explore delegation agent | Absent (superseded by RFC-633) | P3 (unchanged) |
| RFC-619 | `academic_research` Phase 2 | INTAKE_ONLY list only | P3 (unchanged) |
| RFC-622 | Clarification relay + TUI toggle | Partial | P3 (unchanged) |
| RFC-623 | Veritas auto-mode robustness | Partial | P3 (unchanged) |
| RFC-630 | Branch routing §10 | Partial | P3 (unchanged) |
| RFC-606 | DeepAgents migration remaining phases | Partial | P3 (unchanged) |
| RFC-607 | Progressive display refinements | Ongoing | P3 (unchanged) |
| RFC-610 | `soothe_sdk` refactor | PyPI dep (out of scope this repo) | P3 (unchanged) |
| RFC-802 | Persistence refactor migration | Partial | P3 (unchanged) |

## C. Corrected priority summary

| Priority | Before (inventory) | After (corrected) | Δ |
|----------|-------------------|-------------------|---|
| P0 | 2 (RFC-412, RFC-504) | **0** | −2 |
| P1 | 5 (RFC-901, RFC-621, RFC-627, RFC-301, RFC-902) | **2** (RFC-621, RFC-902) | −3 |
| P2 | 10 | **4** (RFC-452, RFC-614, RFC-450, RFC-801) | −6¹ |
| P3 | 19 | 19 | 0 |

¹ RFC-803 promoted out of P2 (was false positive); RFC-450 and RFC-801 remain
P2 pending deeper verification of their specific sub-claims (capability
negotiation versioning, and `SQLiteBackend` formal class hierarchy).

## D. Root cause of false positives

1. **Package DAG not respected** — `MCPRegistry` and `LLMFactory` live in the
   PyPI-owned `soothe_nano` package (per AGENTS.md §7b). The inventory searched
   `packages/` (monorepo) but the symbol is a *dependency*, re-exported via a
   thin alias (`soothe/persistence/unified.py` aliases
   `configure_unified_persistence` from `soothe_nano`). The gap tool's "zero
   hits in packages/" is expected for owned-DAG leaves.

2. **String-literal false negatives** — the inventory's grep for class names
   sometimes missed implementations because the class was defined under a
   different name (e.g. `DaemonPresentationEngine` vs `PresentationEngine`,
   `StrangeLoopCheckpointPersistenceManager` vs `PersistenceManager`,
   `LoopCardLedger` vs `DisplayCardLedger`). The inventory matched the RFC's
   *literal* class name, not the shipped implementation name.

3. **RFC status not consulted** — RFC-627, RFC-632, and RFC-301 all declare
   `Status: Implemented` (or specify only interfaces, not a class). The
   inventory's SNI classification ignored the RFC's own status line.

4. **Submodule scope** — RFC-631's `GoalDisplaySnapshot` lives in
   `soothe_sdk.display.snapshot_types`, imported into the daemon. The
   inventory searched `packages/` but not the `soothe_sdk` PyPI dependency
   that the monorepo re-exports.

## E. Recommended action

1. Update `IG-spec-vs-code-gap-inventory.md` §B to remove the 12 false-positive
   rows listed in §A above.
2. Update `IG-gap-triage-matrix.md` to reflect the corrected priority counts
   (§C).
3. Re-run the gap tool with a search scope that includes `soothe_nano`,
   `soothe_sdk`, and `soothe-deepagents` PyPI packages (not just `packages/`),
   and match by *implementation name* (e.g. `DaemonPresentationEngine`,
   `StrangeLoopCheckpointPersistenceManager`) in addition to RFC literal names.
4. Consult the RFC `Status:` line before classifying as SNI.

## Out of scope

- Implementing any of the verified genuine gaps in §B.
- Changing the gap tool itself (separate task).
