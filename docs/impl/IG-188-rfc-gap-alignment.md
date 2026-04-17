# IG-188: RFC Gap Alignment After 2026-04-17 Brainstorming

**Status**: In Progress  
**Owner**: AI Agent  
**Created**: 2026-04-17  
**Updated**: 2026-04-17 (specs-only gap closure pass)

## Objective

Align RFC documents with brainstorming-derived architecture decisions without changing implementation-status truthfulness.

## Scope

1. Remove cross-RFC ownership ambiguity for GoalBackoffReasoner.
2. Add a canonical shared evidence contract for Layer 2/Layer 3 interoperability.
3. Add experimental adaptive decomposition mode as a bounded architecture extension.
4. Normalize stale cross-references in edited RFCs.
5. **Specs-only gap closure (2026-04-17)**: single source of truth for retrieval API; clarify AgentLoop retrieval authority versus ContextProtocol ownership; document dual-trigger GoalEngine sync; symmetric monitoring patterns; optional knowledge-aware thread routing; non-normative goal-evolution stance and crystallization notes; RFC-000 diagram fix and cross-domain appendix.

## Non-Goals

- No code implementation changes.
- No status inflation (Draft/Implemented remains as currently accurate).
- No renumbering migration outside touched RFC files.

## Planned Edits

- `docs/specs/RFC-200-autonomous-goal-management.md`
  - Canonical ownership note for backoff models.
  - Shared evidence contract section.
  - Experimental adaptive decomposition section.
  - Reference/link cleanup.
- `docs/specs/RFC-201-agentloop-plan-execute-loop.md`
  - Convert backoff section to integration-only view and defer model authority to RFC-200.
  - Update stale RFC links.
- `docs/specs/RFC-207-agentloop-thread-context-lifecycle.md`
  - Reference canonical evidence contract for execution evidence payloads.
- `docs/specs/RFC-001-core-modules-architecture.md`
  - Update related references from legacy RFC-300 to canonical RFC-400/RFC-402.
- `docs/specs/rfc-index.md`
  - Remove legacy RFC-300 from canonical protocol set table.
- `docs/specs/RFC-500-cli-tui-architecture.md`
  - Normalize related/reference links to RFC-400/402/450 and RFC-202.
- `docs/specs/RFC-404-planner-protocol-architecture.md`
  - Normalize Layer 2 references to RFC-201 and GoalEngine reference to RFC-200.
- `docs/specs/RFC-301-protocol-registry.md`
  - Replace RFC-300 references with RFC-400/RFC-402 split references.
- `docs/specs/RFC-204-autopilot-mode.md`
  - Update related links to canonical RFC-201/RFC-202/RFC-450 files.
- `docs/specs/RFC-202-dag-execution.md`
  - Normalize references to RFC-201, RFC-404, RFC-400/402.
- `docs/specs/RFC-602-sqlite-backend.md`
  - Replace RFC-300 dependency/link with RFC-400 + RFC-402.
- `docs/specs/RFC-604-reason-phase-robustness.md`
  - Replace legacy RFC-200-agentic-goal-execution naming with RFC-201-agentloop-plan-execute-loop.
- `docs/specs/RFC-000-system-conceptual-design.md`
  - Layer 2 diagram references RFC-201; Appendix A cross-domain analogies (non-normative).
- `docs/specs/RFC-001-core-modules-architecture.md`
  - Defer `ContextRetrievalModule` to RFC-400; protocol summary includes `get_retrieval_module` pointer.
- `docs/specs/RFC-400-context-protocol-architecture.md`
  - Mark ContextRetrievalModule section as canonical; reference RFC-001 deferral.
- `docs/specs/RFC-201-agentloop-plan-execute-loop.md`
  - Retrieval authority, dual-trigger sync, TaskPackage versus configurable packaging.
- `docs/specs/RFC-207-agentloop-thread-context-lifecycle.md`
  - Report-back symmetric pattern alongside event-driven monitoring.
- `docs/specs/RFC-608-loop-multithread-lifecycle.md`
  - Optional knowledge-aware thread routing dimension.
- `docs/specs/RFC-200-autonomous-goal-management.md`
  - §3.0 goal evolution stance; §3.1 informative signals for adaptive mode.

## Verification

- Ensure internal consistency of model names and ownership language.
- Ensure links point to existing canonical RFC files.
- Specs-only: no `packages/` or `src/` edits for this pass.
