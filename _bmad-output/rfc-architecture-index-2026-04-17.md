# RFC Architecture Index: AgentLoop, GoalEngine, and Related Components

**Generated**: 2026-04-17
**Purpose**: Comprehensive index of all RFCs related to AgentLoop (Layer 2), GoalEngine (Layer 3), CoreAgent (Layer 1), and supporting architectural components.

---

## Core Three-Layer Architecture

### Layer 1: CoreAgent Runtime

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-000** | System Conceptual Design | Draft | Foundation: Three-layer architecture, guiding principles, core abstractions |
| **RFC-001** | Core Modules Architecture | Implemented | 8 core protocols: ContextProtocol, MemoryProtocol, PlannerProtocol, PolicyProtocol, DurabilityProtocol, RemoteAgentProtocol, VectorStoreProtocol, PersistStore |
| **RFC-100** | CoreAgent Runtime | Draft | Layer 1 foundation: create_soothe_agent() → CompiledStateGraph, execution loop |

### Layer 2: Agentic Goal Execution (AgentLoop)

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-201** | Agentic Goal Execution Loop | Implemented | **AgentLoop**: Plan → Execute loop (max ~8 iterations), AgentDecision, PlanResult, iterative refinement |
| **RFC-202** | DAG Execution & Failure Recovery | Implemented | ConcurrencyController, StepScheduler, progressive checkpointing, RunArtifactStore |
| **RFC-203** | Loop Working Memory | Draft | Bounded scratchpad for Plan context, spill artifacts, survives iterations |
| **RFC-205** | Layer 2 Unified State Checkpoint | Draft | LoopState model, wave execution metrics, checkpoint envelope |
| **RFC-609** | Goal Context Management for AgentLoop | Draft | GoalContextManager: previous goal injection, thread switch recovery, Plan vs Execute context separation |
| **RFC-608** | Loop Multi-Thread Lifecycle | Draft | Thread switching, thread health metrics, multi-thread spanning checkpoint |

**AgentLoop Enhancements:**

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-204** | Autopilot Mode | Draft | Autonomous execution mode, autopilot working directory, goal file discovery |
| **RFC-206** | Prompt Architecture | Draft | Plan/Execute prompt structure, context injection patterns |
| **RFC-207** | Message Type Separation | Draft | System vs user vs tool message separation for optimization |
| **RFC-208** | CoreAgent Message Optimization | Draft | Message compression, context window optimization |
| **RFC-209** | Executor Thread Isolation Simplification | Implemented | Remove manual thread ID generation, leverage langgraph concurrency |
| **RFC-210** | Dynamic Tool System Context | Draft | Tool context injection, execution hints middleware |
| **RFC-211** | Layer 2 Tool Result Optimization | Draft | Tool result aggregation, evidence flow optimization |
| **RFC-603** | Reasoning Quality Progressive Actions | Implemented | Progressive Plan decisions, evidence-driven strategy |
| **RFC-604** | Reason Phase Robustness | Implemented | Two-phase Plan architecture (StatusAssessment + PlanGeneration) |

### Layer 3: Autonomous Goal Management (GoalEngine)

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-200** | Autonomous Goal Management Loop | Revised | **GoalEngine**: Goal DAG management, GoalDirective, dynamic restructuring, backoff reasoning (NEW) |
| **RFC-204** | Autopilot Mode | Draft | GoalEngine autopilot integration, GOAL.md discovery, status tracking |

---

## Context and Memory (Consciousness Layer)

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-001** | Core Modules Architecture (Module 1) | Implemented | **ContextProtocol**: Unbounded knowledge accumulator, ingest/project, KeywordContext, VectorContext, retrieval module (NEW) |
| **RFC-001** | Core Modules Architecture (Module 2) | Implemented | **MemoryProtocol**: Cross-thread long-term memory, MemUMemory, semantic recall |
| **RFC-300** | Context & Memory Protocols | Draft | ContextProtocol vs MemoryProtocol separation, persistence patterns |
| **RFC-104** | Dynamic System Context | Draft | System-level context injection, AGENTS.md loading |
| **RFC-203** | Loop Working Memory | Draft | AgentLoop working memory (separate from ContextProtocol) |

---

## Concurrency and Execution Control

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-202** | DAG Execution (ConcurrencyController) | Implemented | Hierarchical semaphore: goal → step → LLM levels, unlimited mode, circuit breaker |
| **RFC-202** | DAG Execution (StepScheduler) | Implemented | DAG-based step scheduling, dependency resolution, cycle detection, ready_steps() |
| **RFC-202** | DAG Execution (RunArtifactStore) | Implemented | Structured run directory, checkpoint envelope, step/goal reports, artifact tracking |
| **RFC-605** | Explore Subagent Parallel Spawning | Draft | Parallel subagent execution patterns, concurrent task spawning |

---

## Planner Protocol

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-001** | Core Modules Architecture (Module 3) | Implemented | **PlannerProtocol**: create_plan, revise_plan, reflect; LLMPlanner implementation |
| **RFC-301** | Protocol Registry | Draft | Protocol implementation registry, SootheConfig protocol resolution |
| **RFC-604** | Reason Phase Robustness | Implemented | Two-phase Plan: StatusAssessment + PlanGeneration, token efficiency |

---

## Policy and Security

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-001** | Core Modules Architecture (Module 4) | Implemented | **PolicyProtocol**: check, narrow_for_child; ConfigDrivenPolicy implementation |
| **RFC-102** | Security: Filesystem Policy | Draft | Least-privilege filesystem access, permission scopes |
| **RFC-101** | Tool Interface | Draft | Tool protocol, tool execution policy integration |

---

## Durability and Persistence

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-001** | Core Modules Architecture (Module 5) | Implemented | **DurabilityProtocol**: create_thread, resume_thread, suspend_thread, archive_thread |
| **RFC-202** | DAG Execution (CheckpointEnvelope) | Implemented | Progressive checkpoint model, goal/plan/step state serialization, recovery flow |
| **RFC-602** | SQLite Backend | Draft | SQLite-based durability implementation |
| **RFC-205** | Layer 2 Unified State Checkpoint | Draft | LoopState checkpoint model, thread lifecycle persistence |

---

## Remote Agents and Interop

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-001** | Core Modules Architecture (Module 6) | Implemented | **RemoteAgentProtocol**: invoke, stream, health_check; LangGraphRemoteAgent implementation |
| **RFC-600** | Plugin Extension System | Implemented | Plugin architecture, event registration, tool/subagent plugins |

---

## Thread and Workspace Management

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-103** | Thread-Aware Workspace | Draft | Workspace per thread isolation, filesystem boundaries |
| **RFC-402** | Unified Thread Management | Draft | Thread lifecycle management, thread metadata, thread filtering |
| **RFC-608** | Loop Multi-Thread Lifecycle | Draft | Thread switching within AgentLoop, thread health metrics |

---

## Event System

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-401** | Event Processing | Implemented | Event filtering, event routing, stream event definitions |
| **RFC-403** | Unified Event Naming | Implemented | Event naming conventions, event type hierarchy |
| **RFC-600** | Plugin Extension System (Events) | Implemented | Event registration API, plugin events, event catalog |

---

## Display and Output

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-500** | CLI/TUI Architecture | Draft | CLI + TUI architecture, WebSocket daemon client |
| **RFC-501** | Display Verbosity | Draft | Output verbosity levels, progressive display |
| **RFC-502** | Unified Presentation Engine | Draft | Unified display engine, event-driven rendering |
| **RFC-607** | Progressive Display Refinements | Implemented | TUI step tree display, progress visualization |

---

## Slash Commands and Skills

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-404** | Slash Command Architecture | Draft | Slash command integration, command routing |
| **RFC-601** | Built-in Agents | Draft | Built-in agent skills, default agent configurations |
| **RFC-600** | Plugin Extension System (Skills) | Implemented | Skills middleware, SKILL.md discovery, skill loading |

---

## Daemon and Communication

| RFC | Title | Status | Description |
|-----|-------|--------|-------------|
| **RFC-400** | Daemon Communication Protocol | Draft | Multi-transport daemon (Unix socket, WebSocket, HTTP REST) |
| **RFC-606** | Deepagents CLI/TUI Migration | Implemented | Migration from soothe SDK to deepagents CLI/TUI |

---

## Summary Statistics

| Category | RFC Count | Key Components |
|----------|-----------|----------------|
| **Three-Layer Architecture** | 10 | CoreAgent (L1), AgentLoop (L2), GoalEngine (L3) |
| **Context & Memory** | 5 | ContextProtocol (consciousness), MemoryProtocol, Working Memory |
| **Concurrency & Execution** | 4 | ConcurrencyController, StepScheduler, DAG execution |
| **Planner Protocol** | 3 | PlannerProtocol, LLMPlanner, two-phase Plan |
| **Policy & Security** | 3 | PolicyProtocol, filesystem policy, tool policy |
| **Durability & Persistence** | 4 | DurabilityProtocol, checkpoint envelope, recovery |
| **Remote Agents** | 2 | RemoteAgentProtocol, plugin system |
| **Thread Management** | 3 | Thread workspace, thread lifecycle, thread switching |
| **Event System** | 3 | Event processing, event naming, event registration |
| **Display & Output** | 4 | CLI/TUI, verbosity, presentation engine |
| **Commands & Skills** | 3 | Slash commands, built-in agents, skills middleware |
| **Daemon & Communication** | 2 | Daemon protocol, CLI/TUI migration |

**Total**: 41 RFCs identified

---

## Architectural Component Mapping

### AgentLoop (Layer 2) Component RFCs

```
AgentLoop Core:
├─ RFC-201: Plan → Execute loop, AgentDecision, PlanResult
├─ RFC-205: LoopState unified model, wave metrics
├─ RFC-608: Multi-thread lifecycle, thread switching
└─ RFC-609: Goal context manager, previous goal injection

AgentLoop Enhancements:
├─ RFC-203: Loop working memory (bounded scratchpad)
├─ RFC-206: Prompt architecture (Plan/Execute prompts)
├─ RFC-209: Executor thread isolation (langgraph native)
├─ RFC-603: Reasoning quality (progressive actions)
└─ RFC-604: Reason phase robustness (two-phase Plan)

AgentLoop Execution:
├─ RFC-202: DAG execution, StepScheduler, concurrency
├─ RFC-210: Dynamic tool system context
├─ RFC-211: Tool result optimization
└─ RFC-605: Subagent parallel spawning
```

### GoalEngine (Layer 3) Component RFCs

```
GoalEngine Core:
├─ RFC-200: Goal DAG management, GoalDirective
├─ RFC-200 (NEW): GoalBackoffReasoner, LLM-driven backoff
└─ RFC-204: Autopilot mode, goal file discovery

GoalEngine Integration:
├─ RFC-201: AgentLoop delegation (PERFORM → Layer 2)
├─ RFC-202: Goal DAG scheduling, ready_goals()
└─ RFC-609: Goal context for AgentLoop
```

### ContextProtocol (Consciousness) Component RFCs

```
ContextProtocol Core:
├─ RFC-001 (Module 1): ContextProtocol, ingest/project
├─ RFC-001 (NEW): ContextRetrievalModule, goal-centric retrieval
└─ RFC-300: Context vs Memory separation

Context Integration:
├─ RFC-203: Loop working memory (separate bounded layer)
├─ RFC-104: Dynamic system context (AGENTS.md)
└─ RFC-609: Goal context injection into AgentLoop
```

### CoreAgent (Layer 1) Component RFCs

```
CoreAgent Core:
├─ RFC-100: CoreAgent runtime, create_soothe_agent()
├─ RFC-208: Message optimization
└─ RFC-207: Message type separation

CoreAgent Integration:
├─ RFC-201: AgentLoop execution (Execute → CoreAgent)
├─ RFC-209: Thread isolation (langgraph concurrency)
└─ RFC-210: Dynamic tool system context
```

---

## Implementation Status Summary

| Status | RFC Count | Examples |
|--------|-----------|----------|
| **Implemented** | 15 | RFC-001, RFC-201, RFC-202, RFC-600, RFC-604, RFC-209 |
| **Revised** | 1 | RFC-200 (updated with backoff reasoning) |
| **Draft** | 25 | RFC-100, RFC-203, RFC-205, RFC-609, RFC-608 |
| **Total** | 41 | All architecture-related RFCs |

---

## References

- **RFC Index**: `docs/specs/rfc-index.md` (complete RFC catalog)
- **RFC Standard**: `docs/specs/rfc-standard.md` (RFC kinds and process)
- **Brainstorming Session**: `_bmad-output/brainstorming/brainstorming-session-2026-04-17-144552.md`
- **IG-184**: `docs/impl/IG-184-architecture-refinement-proposals.md`

---

## Quick Navigation by Layer

**Layer 1 (CoreAgent)**: RFC-100, RFC-208, RFC-209, RFC-210, RFC-207
**Layer 2 (AgentLoop)**: RFC-201, RFC-202, RFC-203, RFC-205, RFC-603, RFC-604, RFC-608, RFC-609, RFC-211
**Layer 3 (GoalEngine)**: RFC-200, RFC-204
**Protocols**: RFC-001 (Context, Memory, Planner, Policy, Durability, RemoteAgent, VectorStore)
**Concurrency**: RFC-202 (ConcurrencyController, StepScheduler)
**Events**: RFC-401, RFC-403, RFC-600
**Display**: RFC-500, RFC-501, RFC-502, RFC-607

---

*Index complete: 41 RFCs mapped to AgentLoop, GoalEngine, CoreAgent, and architectural components.*