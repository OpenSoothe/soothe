# IG-188: RFC Gap Alignment After 2026-04-17 Brainstorming

**Status**: In Progress  
**Owner**: AI Agent  
**Created**: 2026-04-17

## Objective

Align RFC documents with brainstorming-derived architecture decisions without changing implementation-status truthfulness.

## Scope

1. Remove cross-RFC ownership ambiguity for GoalBackoffReasoner.
2. Add a canonical shared evidence contract for Layer 2/Layer 3 interoperability.
3. Add experimental adaptive decomposition mode as a bounded architecture extension.
4. Normalize stale cross-references in edited RFCs.

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

## Verification

- Ensure internal consistency of model names and ownership language.
- Ensure links point to existing canonical RFC files.
