# RFC Index

This index reflects the post-consolidation RFC set and defines which files are canonical for active architecture and implementation decisions.

## Consolidation Rule

- Canonical merged RFCs use short numeric names such as `RFC-201-agentloop-plan-execute-loop.md` and `RFC-400-context-protocol-architecture.md`.
- Legacy numbered documents with descriptive suffixes remain for history and migration context.
- Alias files were removed during consolidation cleanup.

---

## Canonical RFC Set

### Foundation

| RFC | File | Purpose |
|-----|------|---------|
| RFC-000 | [RFC-000-system-conceptual-design.md](./RFC-000-system-conceptual-design.md) | System conceptual design and principles |
| RFC-001 | [RFC-001-core-modules-architecture.md](./RFC-001-core-modules-architecture.md) | Core modules and protocol decomposition |

### Core Runtime

| RFC | File | Purpose |
|-----|------|---------|
| RFC-100 | [RFC-100-coreagent-runtime.md](./RFC-100-coreagent-runtime.md) | CoreAgent runtime and execution base |
| RFC-101 | [RFC-101-tool-interface.md](./RFC-101-tool-interface.md) | Tool contracts and execution interface |
| RFC-102 | [RFC-102-security-filesystem-policy.md](./RFC-102-security-filesystem-policy.md) | Security and filesystem policy controls |
| RFC-103 | [RFC-103-thread-aware-workspace.md](./RFC-103-thread-aware-workspace.md) | Thread-aware workspace behavior |
| RFC-104 | [RFC-104-dynamic-system-context.md](./RFC-104-dynamic-system-context.md) | Dynamic system context injection |

### AgentLoop and Goal Execution

| RFC | File | Purpose |
|-----|------|---------|
| RFC-200 | [RFC-200-autonomous-goal-management.md](./RFC-200-autonomous-goal-management.md) | Layer 3 autonomous goal management |
| RFC-201 | [RFC-201-agentloop-plan-execute-loop.md](./RFC-201-agentloop-plan-execute-loop.md) | Unified AgentLoop core loop (Layer 2) (merged) |
| RFC-203 | [RFC-203-agentloop-state-memory.md](./RFC-203-agentloop-state-memory.md) | Unified AgentLoop state and working memory (merged) |
| RFC-206 | [RFC-206-prompt-architecture.md](./RFC-206-prompt-architecture.md) | Prompt architecture and composition |
| RFC-207 | [RFC-207-agentloop-thread-context-lifecycle.md](./RFC-207-agentloop-thread-context-lifecycle.md) | Unified thread and context lifecycle (merged) |
| RFC-211 | [RFC-211-layer2-tool-result-optimization.md](./RFC-211-layer2-tool-result-optimization.md) | Tool result and evidence optimization |
| RFC-213 | [RFC-213-agentloop-reasoning-quality.md](./RFC-213-agentloop-reasoning-quality.md) | Unified reasoning quality model (merged) |

### Core Protocols

| RFC | File | Purpose |
|-----|------|---------|
| RFC-300 | [RFC-300-context-memory-protocols.md](./RFC-300-context-memory-protocols.md) | Context and memory protocol contracts |
| RFC-301 | [RFC-301-protocol-registry.md](./RFC-301-protocol-registry.md) | Protocol registration and resolution |
| RFC-400 | [RFC-400-context-protocol-architecture.md](./RFC-400-context-protocol-architecture.md) | Unified context protocol and retrieval (merged) |
| RFC-402 | [RFC-402-memory-protocol-architecture.md](./RFC-402-memory-protocol-architecture.md) | Unified memory protocol and separation (merged) |
| RFC-404 | [RFC-404-planner-protocol-architecture.md](./RFC-404-planner-protocol-architecture.md) | Unified planner protocol and planning pattern (merged) |
| RFC-406 | [RFC-406-policy-protocol-architecture.md](./RFC-406-policy-protocol-architecture.md) | Unified policy protocol and permissions (merged) |
| RFC-408 | [RFC-408-durability-protocol-architecture.md](./RFC-408-durability-protocol-architecture.md) | Unified durability protocol (merged) |
| RFC-410 | [RFC-410-remote-agent-protocol-architecture.md](./RFC-410-remote-agent-protocol-architecture.md) | Unified remote agent protocol and backends (merged) |

### Daemon, UX, Plugins

| RFC | File | Purpose |
|-----|------|---------|
| RFC-500 | [RFC-500-cli-tui-architecture.md](./RFC-500-cli-tui-architecture.md) | CLI/TUI architecture |
| RFC-450 | [RFC-450-daemon-communication-protocol.md](./RFC-450-daemon-communication-protocol.md) | Unified daemon communication |
| RFC-401 | [RFC-401-event-processing.md](./RFC-401-event-processing.md) | Event processing and filtering |
| RFC-452 | [RFC-452-unified-thread-management.md](./RFC-452-unified-thread-management.md) | Unified thread management architecture |
| RFC-403 | [RFC-403-unified-event-naming.md](./RFC-403-unified-event-naming.md) | Unified event naming semantics |
| RFC-454 | [RFC-454-slash-command-architecture.md](./RFC-454-slash-command-architecture.md) | Slash command architecture |
| RFC-501 | [RFC-501-display-verbosity.md](./RFC-501-display-verbosity.md) | Display and verbosity controls |
| RFC-502 | [RFC-502-unified-presentation-engine.md](./RFC-502-unified-presentation-engine.md) | Unified presentation pipeline |
| RFC-600 | [RFC-600-plugin-extension-system.md](./RFC-600-plugin-extension-system.md) | Plugin extension model |
| RFC-601 | [RFC-601-built-in-agents.md](./RFC-601-built-in-agents.md) | Built-in agents and plugin packaging |
| RFC-602 | [RFC-602-sqlite-backend.md](./RFC-602-sqlite-backend.md) | SQLite backend specification |
| RFC-603 | [RFC-603-reasoning-quality-progressive-actions.md](./RFC-603-reasoning-quality-progressive-actions.md) | Reasoning quality actions |
| RFC-604 | [RFC-604-reason-phase-robustness.md](./RFC-604-reason-phase-robustness.md) | Plan robustness mechanisms |
| RFC-605 | [RFC-605-explore-subagent-parallel-spawning.md](./RFC-605-explore-subagent-parallel-spawning.md) | Subagent and parallel spawning strategy |
| RFC-606 | [RFC-606-deepagents-cli-tui-migration.md](./RFC-606-deepagents-cli-tui-migration.md) | CLI/TUI migration strategy |
| RFC-607 | [RFC-607-progressive-display-refinements.md](./RFC-607-progressive-display-refinements.md) | Progressive UX refinements |
| RFC-608 | [RFC-608-loop-multithread-lifecycle.md](./RFC-608-loop-multithread-lifecycle.md) | Multi-thread lifecycle for loop execution |
| RFC-609 | [RFC-609-goal-context-management.md](./RFC-609-goal-context-management.md) | Goal context management |
| RFC-610 | [RFC-610-sdk-module-structure-refactoring.md](./RFC-610-sdk-module-structure-refactoring.md) | SDK module structure refactor |

---

## Legacy Navigation

- Legacy documents remain in `docs/specs/` with descriptive filenames such as:
  - `RFC-200-autonomous-goal-management.md` (Layer 3)
  - `RFC-204-autopilot-mode.md` (Autopilot extension)
  - `RFC-202-dag-execution.md` (superseded by `RFC-201-agentloop-plan-execute-loop.md` / `RFC-203-agentloop-state-memory.md`)
- Use explicit redirects inside legacy files to find merged RFC targets.

---

## Three-Component Execution Model

- `GoalEngine`: strategic autonomous goal management.
- `AgentLoop`: iterative goal execution and state progression.
- `CoreAgent`: tool/subagent runtime and message handling.

---

## Related Documents

- [RFC Standard](./rfc-standard.md)
- [RFC History](./rfc-history.md)
- [RFC Naming](./rfc-namings.md)

---

## Recent Changes (2026-04-17)

**RFC Consolidation Complete**: Numbering conflicts and cross-reference drift were resolved; protocol and daemon tracks are explicitly separated in this index.