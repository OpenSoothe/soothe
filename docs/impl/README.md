# Implementation Guides

This directory contains implementation guides for features and components defined in the RFC specifications.

## Purpose

Implementation guides translate RFC specifications into concrete implementation plans with:

- Detailed file structure
- Code implementation steps
- Testing strategies
- Migration notes (if applicable)
- Verification checklists

## Structure

Each implementation guide follows the template in `templates/impl-guide-template.md` and includes:

1. **Overview** - What the guide covers
2. **Implementation Plan** - Phased approach with tasks
3. **File Structure** - Directory and file organization
4. **Implementation Details** - Code-level guidance
5. **Testing Strategy** - Unit and integration testing approach
6. **Verification** - Checklist for completion

## Relationship to RFCs

- **RFCs** define *what* to build (design, interfaces, contracts)
- **Implementation Guides** define *how* to build it (concrete code, file structure, tests)

## Current Guides

- [IG-001: Soothe Setup and Migration](001-soothe-setup-migration.md)
- [IG-002: Soothe Polish](002-soothe-polish.md)
- [IG-003: Streaming Examples](003-streaming-examples.md)
- [IG-004: Ecosystem Capability Analysis](004-ecosystem-capability-analysis.md)
- [IG-005: Core Protocols Implementation](005-core-protocols-implementation.md)
- [IG-006: VectorStore, Router, Persistence](006-vectorstore-router-persistence.md)
- [IG-007: CLI TUI Implementation](007-cli-tui-implementation.md)
- [IG-008: Config and Docs Revision](008-config-docs-revision.md)
- [IG-009: Ollama Provider](009-ollama-provider.md)
- [IG-010: Textual TUI and Daemon Implementation](010-tui-layout-history-refresh.md)
- [IG-011: Skillify Agent Implementation](011-skillify-agent-implementation.md)
- [IG-012: Weaver Agent Implementation](012-weaver-agent-implementation.md)
- [IG-013: Soothe Polish Pass](013-soothe-polish-pass.md)
- [IG-014: Code Structure Revision](014-code-structure-revision.md)
- [IG-015: RFC Gap Closure and Compat Hard Cut](015-rfc-gap-closure-and-compat-hard-cut.md)
- [IG-016: Agent Optimization Pass](016-agent-optimization-pass.md)
- [IG-017: Progress Events Tools Polish](017-progress-events-tools-polish.md)
- [IG-018: Autonomous Iteration Loop](018-autonomous-iteration-loop.md)
- [IG-019: Soothe Tools Enhancement](019-soothe-tools-enhancement.md)
- [IG-020: Detached Daemon Autonomous Capability](020-detached-daemon-autonomous-capability.md)
- [IG-021: Performance Optimization Implementation](021-performance-optimization-implementation.md)
- [IG-021: Daemon Lifecycle Fixes](021-daemon-lifecycle-fixes.md)
- [IG-022: Unified Persistence Storage](022-unified-persistence-storage.md)
- [IG-023: Postgres DB Separation and Persistence Deadlock Fix](023-postgres-db-separation-and-persistence-deadlock-fix.md)
- [IG-024: Existing Browser Connection](024-existing-browser-connection.md)
- [IG-025: Subagent Progress Visibility and Output Capture](025-subagent-progress-visibility.md)
- [IG-026: Planning Workflow Refactoring](036-planning-workflow-refactoring.md)
- [IG-128: Layer 2 Reason — thread context and TUI completion display](IG-128-loop-reason-prior-conversation.md)
- [IG-129: TUI debug trace (logging + tests)](IG-129-tui-debug-trace.md)

## Related Documents

- [RFC Index](../specs/rfc-index.md) - All RFC specifications
- [RFC Standard](../specs/rfc-standard.md) - Specification kinds

---

*Directory created by platonic-init*
