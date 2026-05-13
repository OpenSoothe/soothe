# RFC References Extracted from RFC-000 to RFC-299

## Summary

This document contains all markdown links and RFC references extracted from RFC files 000-299 (core system + agent loop).

---

## RFC-000: System Conceptual Design

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-200 | Layer 3: Autonomous Goal Management | Three-layer architecture |
| RFC-201 | Layer 2: Agentic Goal Execution | Three-layer architecture |
| RFC-100 | Layer 1: CoreAgent Runtime | Three-layer architecture |
| RFC-604 | Plan phase two-phase architecture | Plan-driven execution principle |
| RFC-403 | Event naming prefix | Wire events prefix |
| RFC-001 | ContextProtocol consciousness | Architectural component isolation |
| RFC-201 §50-60 | AgentLoop role clarification | See also reference |
| RFC-201 §61-66 | Retrieval authority clarification | See also reference |
| RFC-001 §14-47 | ContextProtocol consciousness concept | See also reference |

### Markdown Links (Related Documents Section)
```markdown
- [RFC-200](./RFC-200-autonomous-goal-management.md) - Layer 3: Autonomous Goal Management
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Layer 2: AgentLoop Plan-Execute Loop
- [RFC-400](./RFC-400-context-protocol-architecture.md) through [RFC-408](./RFC-408-durability-protocol-architecture.md) - Core protocol architecture set
```

---

## RFC-001: Core Modules Architecture

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-000 | System Conceptual Design | Related |
| RFC-200 | Goal Management | Related |
| RFC-400 | ContextProtocol | Canonical retrieval surface |
| RFC-402 | MemoryProtocol | Related |
| RFC-201 §61-78 | AgentLoop operational authority | Retrieval timing |
| RFC-400 | ContextRetrievalModule | Implementation status |
| RFC-200 | StepScheduler | DAG-based execution |
| RFC-604 | Two-phase Plan architecture | LLMPlanner implementation |

### Markdown Links (Protocol Module Table)
```markdown
| **Module 1** | ContextProtocol | [RFC-400](./RFC-400-context-protocol-architecture.md) | Draft |
| **Module 2** | MemoryProtocol | [RFC-402](./RFC-402-memory-protocol-architecture.md) | Draft |
| **Module 3** | PlannerProtocol | [RFC-404](./RFC-404-planner-protocol-architecture.md) | Draft |
| **Module 4** | PolicyProtocol | [RFC-406](./RFC-406-policy-protocol-architecture.md) | Draft |
| **Module 5** | DurabilityProtocol | [RFC-408](./RFC-408-durability-protocol-architecture.md) | Draft |
```

---

## RFC-100: CoreAgent Runtime

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-000 | System Conceptual Design | Dependencies |
| RFC-001 | Core Modules Architecture | Dependencies |
| RFC-200 | Layer 3 Autonomous Goal Management | Three-layer model |
| RFC-207 | Thread Naming simplification | Parent/goal thread naming |
| RFC-101 | Tool Interface | Execution tools |
| RFC-601 | Research tools | Built-in capabilities |
| RFC-601 | Skillify subagent | Built-in capabilities |
| RFC-601 | Weaver subagent | Built-in capabilities |

---

## RFC-101: Tool Interface

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-401 | Event Processing | Dependencies |
| RFC-0016 | Superseded | Tool interface optimization |
| RFC-0025 | Superseded | Tool event naming unification |
| RFC-400 | Event Processing Pipeline | Non-goals reference |
| RFC-102 | Security Policy | Non-goals reference |
| RFC-500 | CLI/TUI Architecture | References section |

---

## RFC-102: Security Filesystem Policy

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-001 | Policy System | Depends On |

---

## RFC-103: Thread-Aware Workspace

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-102 | Security Filesystem Policy | Depends On |
| RFC-450 | Daemon Communication | Depends On |
| RFC-452 | Thread Management | Depends On |
| RFC-102 | Existing security model | Implementation |

### Markdown Links (References Section)
```markdown
- RFC-102: Secure Filesystem Path Handling
- RFC-400: Daemon Communication Protocol
- RFC-402: Unified Thread Management
```

---

## RFC-104: Dynamic System Context Injection

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-100 | CoreAgent Runtime | Depends On |
| RFC-101 | Tool Interface | Depends On |
| RFC-103 | Thread-Aware Workspace | Depends On |
| RFC-214 | Volatility-Tiered Prompt Architecture | Amendment |
| RFC-207 | SOOTHE_ prefix removal | Amendment reference |

### Markdown Links (References Section)
```markdown
- RFC-100: CoreAgent Runtime
- RFC-101: Tool Interface
- RFC-103: Thread-Aware Workspace
- RFC-102: Security Filesystem Policy
```

---

## RFC-200: Autonomous Goal Management

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-000 | System Conceptual Design | Dependencies |
| RFC-001 | Core Modules Architecture | Dependencies |
| RFC-500 | CLI/TUI Architecture | Dependencies |
| RFC-201 | AgentLoop Plan-Execute | Dependencies |
| RFC-0011 | Superseded | Dynamic Goal Management |
| RFC-201 | Layer 2 Agentic Goal Execution | Three-layer model |
| RFC-100 | Layer 1 CoreAgent Runtime | Three-layer model |
| RFC-200 §14-22 | EvidenceBundle contract | Goal failure |
| RFC-201 §236-245 | Wave metrics | EvidenceBundle |
| RFC-200 | EvidenceBundle canonical structure | EvidenceBundle contract |

### Markdown Links (References Section)
```markdown
- [RFC-000](./RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) - Core Modules Architecture
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Layer 2: AgentLoop Plan-Execute Loop
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Unified AgentLoop execution
```

---

## RFC-201: AgentLoop Plan-Execute Loop

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-000 | System Conceptual Design | Dependencies |
| RFC-001 | Core Modules Architecture | Dependencies |
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-203 | State | Related |
| RFC-207 | Thread | Related |
| RFC-213 | Reasoning | Related |
| RFC-200 | Layer 3 Autonomous Goal Management | Three-layer model |
| RFC-001 | ContextProtocol ownership | Context retrieval |
| RFC-400 | ContextRetrievalModule | Retrieval module implementation |
| RFC-400 | Canonical retrieval API | Reference note |
| RFC-200 | Layer 3 GoalEngine | Integration |
| RFC-207 | Thread isolation simplification | Context isolation |
| RFC-207 | Executor thread isolation | Mechanism note |
| RFC-200 §14-22 | EvidenceBundle | Shared contract |
| RFC-500 | CLI/TUI Architecture | TUI routing |
| RFC-614 | Streaming Messaging | Wire format |

### Markdown Links (References Section)
```markdown
- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-100: CoreAgent runtime
- RFC-200: Layer 3 Goal management and backoff authority
- RFC-203: AgentLoop State & Memory Architecture
- RFC-207: AgentLoop Thread Management & Goal Context
- RFC-213: AgentLoop Reasoning Quality & Robustness
```

---

## RFC-203: AgentLoop State & Memory

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-201 | AgentLoop Plan-Execute | Dependencies |
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-207 | Thread | Related |
| RFC-213 | Reasoning | Related |
| RFC-400 | ContextProtocol | Not a second context ledger |
| RFC-200 | AgentLoop Plan-Execute | References |
| RFC-207 | Thread Management | References |
| RFC-400 | ContextProtocol | References |

### Markdown Links (References Section)
```markdown
- RFC-200: AgentLoop Plan-Execute Loop Architecture
- RFC-100: CoreAgent Runtime
- RFC-207: AgentLoop Thread Management & Goal Context
- RFC-400: ContextProtocol (separate unbounded knowledge system)
```

---

## RFC-204: Autopilot Mode

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-200 | Layer 3 Autonomous Goal Management | Dependencies |
| RFC-201 | AgentLoop Plan-Execute | Dependencies |
| RFC-203 | AgentLoop State & Memory | Dependencies |
| RFC-451 | Daemon Communication | Dependencies |
| RFC-500 | CLI/TUI Architecture | Dependencies |
| RFC-200 | Layer 3 Foundation | Relationship table |

### Markdown Links (References Section)
```markdown
- [RFC-200](./RFC-200-autonomous-goal-management.md) — Layer 3 Foundation
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) — Layer 2 Execution
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) — Unified AgentLoop execution
- [RFC-450](./RFC-450-daemon-communication-protocol.md) — Daemon Protocol
- [RFC-500](./RFC-500-cli-tui-architecture.md) — CLI/TUI Architecture
```

---

## RFC-206: Hierarchical Prompt Architecture

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-200 | Layer 2 Agentic Goal Execution | Dependencies |
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-214 | Volatility-Tiered Prompt | Dependencies |
| RFC-183 | Prefetch layout | Tree reference |
| RFC-604 | LLMPlanner | Implementation |
| RFC-214 | Amendment | Volatility-tiered |

### Markdown Links (References Section)
```markdown
- **RFC-200**: Layer 2 Agentic Goal Execution
- **RFC-100**: Layer 1 CoreAgent Runtime
```

---

## RFC-207: AgentLoop Thread Management

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-201 | AgentLoop Plan-Execute | Dependencies |
| RFC-203 | AgentLoop State & Memory | Dependencies |
| RFC-216 | Multi-Thread Lifecycle | Dependencies |
| RFC-213 | Reasoning | Related |
| RFC-200 | EvidenceBundle | Failure diagnosis |
| RFC-203 | Push/pull patterns | Checkpoint updates |
| RFC-216 | GoalExecutionRecord | Goal context |
| RFC-217 | Goal Context Management | References |

### Markdown Links (References Section)
```markdown
- RFC-201: AgentLoop Plan-Execute Loop Architecture
- RFC-203: AgentLoop State & Memory Architecture
- RFC-216: Loop Multi-Thread Lifecycle (original source)
- RFC-217: Goal Context Management (original source)
```

---

## RFC-211: Layer 2 Tool Result Optimization

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-200 | Layer 2 Agentic Goal Execution | Dependencies |
| RFC-100 | Layer 1 CoreAgent Runtime | Dependencies |
| RFC-203 | Layer 2 Unified State Checkpoint | Dependencies |
| RFC-207 | Message Type Separation | Dependencies |
| RFC-207 | Executor Thread Isolation | Dependencies |
| RFC-207 | Dynamic Tool System Context | Dependencies |

### Markdown Links (References Section)
```markdown
- RFC-200: Layer 2 Agentic Goal Execution
- RFC-100: Layer 1 CoreAgent Runtime
- RFC-203: Layer 2 Unified State Checkpoint
- RFC-207: Message Type Separation
- RFC-207: Executor Thread Isolation Simplification
- RFC-207: Dynamic Tool System Context
```

---

## RFC-213: AgentLoop Reasoning Quality

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-200 | AgentLoop Plan-Execute | Dependencies |
| RFC-203 | AgentLoop State & Memory | Dependencies |
| RFC-207 | Thread | Related |
| RFC-214 | Plan-context human | Related |
| RFC-603 | Reasoning Quality Progressive | Related |
| RFC-604 | Plan Phase Robustness | Related |
| IG-376 | Implementation guide | Related |
| RFC-604 §7.2 | PlanResult merge | Two-phase architecture |
| RFC-604 | Normative field lists | StatusAssessment |
| RFC-603 §3.2 | Goal progress | Assess-model output |
| RFC-214 | Loop message surface | Plan context |

### Markdown Links (References Section)
```markdown
- RFC-200: AgentLoop Plan-Execute Loop Architecture
- RFC-203: AgentLoop State & Memory Architecture
- RFC-603: Reasoning Quality Progressive Actions
- RFC-604: Plan Phase Robustness
- RFC-214: Loop message surface
```

---

## RFC-214: Volatility-Tiered Prompt Architecture

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-206 | Prompt Architecture | Dependencies |
| RFC-104 | Dynamic System Context | Dependencies |
| RFC-207 | Thread & Goal Context | Dependencies |
| RFC-203 | AgentLoop State & Memory | Dependencies |
| RFC-215 | AgentLoop Persistence | Dependencies |
| RFC-218 | Checkpoint Tree | Dependencies |
| RFC-216 | Multi-Thread Lifecycle | Dependencies |
| RFC-217 | Goal Context Management | Dependencies |
| RFC-211 | Tool Result Shaping | Related |
| RFC-213 | AgentLoop Reasoning Quality | Related |
| RFC-220 | LangGraph Agent Loop | Related |
| RFC-614 | Streaming Messaging | Related |
| RFC-215 | SQLite/PostgreSQL | Checkpoints |
| RFC-104 | Amendment | Dynamic System Context |
| RFC-206 | Amendment | Hierarchical Prompt |
| RFC-217 | Amendment | Goal Context Management |

### Markdown Links (Changelog)
```markdown
| 2026-05-08 | Major revision: volatility-tiered prompt architecture, user message envelope, complete ledger with plan-assess/plan-generate phases, CoreAgent isolation, reference-based dedup, cache optimization, G9-G11, amendments to RFC-104/206/217 |
```

---

## RFC-215: AgentLoop Persistence Backend

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-216 | Multi-Thread Lifecycle | Dependencies |
| RFC-218 | Checkpoint Tree | Dependencies |
| RFC-503 | Loop-First UX | Dependencies |
| RFC-218 | Checkpoint Tree | References |
| RFC-216 | Multi-Thread Lifecycle | References |
| RFC-503 | Loop-First UX | References |
| RFC-411 | Event Stream Replay | References |
| RFC-602 | SQLite Backend | References |

### Markdown Links (References Section)
```markdown
- RFC-218: AgentLoop Checkpoint Tree Architecture
- RFC-216: AgentLoop Multi-Thread Lifecycle
- RFC-503: Loop-First User Experience
- RFC-411: Event Stream Replay
- RFC-602: SQLite Backend (existing)
```

---

## RFC-216: AgentLoop Multi-Thread Lifecycle

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-203 | Layer 2 Unified State Model | Dependencies |
| RFC-201 | Agentic Goal Execution | Dependencies |
| RFC-217 | Thread-relationship options | Knowledge-aware routing |
| RFC-203 | Layer 2 Unified State Model | Extension |
| RFC-201 | Agentic Goal Execution | Extension |
| RFC-203 | Loop Working Memory | References |
| RFC-002 | MemoryProtocol | References |
| RFC-103 | VectorStoreProtocol | References |

### Markdown Links (References Section)
```markdown
- RFC-203: Layer 2 Unified State Model
- RFC-200: Agentic Goal Execution
- RFC-203: Loop Working Memory
- RFC-002: MemoryProtocol
- RFC-103: VectorStoreProtocol
```

---

## RFC-217: Goal Context Management

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-201 | Agentic Goal Execution | Dependencies |
| RFC-216 | Multi-Thread Lifecycle | Dependencies |
| RFC-203 | Layer 2 Unified State Model | Dependencies |
| RFC-216 | Thread switching | Problem statement |
| RFC-216 | GoalExecutionRecord | Integration |
| RFC-200 | Agentic Goal Execution Loop | References |
| RFC-216 | Multi-Thread Lifecycle | References |
| RFC-203 | Layer 2 Unified State Model | References |
| RFC-214 | Amendment | Complete Ledger |

### Markdown Links (References Section)
```markdown
- RFC-200: Agentic Goal Execution Loop
- RFC-216: AgentLoop Multi-Thread Infinite Lifecycle
- RFC-203: Layer 2 Unified State Model
```

---

## RFC-218: AgentLoop Checkpoint Tree

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-216 | Multi-Thread Lifecycle | Dependencies |
| IG-238 | Checkpoint Unified Integration | Dependencies |
| RFC-216 | Identity fields | Data model |
| RFC-216 | Status | Data model |
| RFC-216 | Goal execution history | Data model |
| RFC-216 | Working memory | Data model |
| RFC-216 | Thread health | Data model |
| RFC-217 | Goal context injection | Data model |
| RFC-216 | Multi-Thread Lifecycle | References |
| RFC-215 | Persistence Backend | References |
| RFC-411 | Event Stream Replay | References |

### Markdown Links (References Section)
```markdown
- RFC-216: AgentLoop Multi-Thread Lifecycle
- RFC-215: AgentLoop Persistence Backend
- RFC-411: Event Stream Replay & History Reconstruction
```

---

## RFC-219: Goal Completion Module

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-201 | AgentLoop Plan-Execute | Dependencies |
| RFC-603 | Reasoning Quality | Dependencies |
| RFC-201 §90-97 | Adaptive final user response | Current issues |
| RFC-001 §28 | Separation of concerns | Architecture violation |
| RFC-500 | CLI/TUI Architecture | Runner wire |
| RFC-614 | Streaming Messaging | Runner wire |
| IG-343 | Implementation guide | Runner wire |
| RFC-201 §90-97 | Adaptive final user response | References |
| RFC-603 | Synthesis phase | References |

### Markdown Links (References Section)
```markdown
- RFC-201 §90-97: Adaptive final user response (original description)
- RFC-603: Synthesis phase (evidence-based triggers)
```

---

## RFC-220: LangGraph Agent Loop Orchestrator

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-000 | System Conceptual Design | Dependencies |
| RFC-001 | Core Modules Architecture | Dependencies |
| RFC-100 | CoreAgent Runtime | Dependencies |
| RFC-604 | Plan Phase Robustness | Dependencies |
| RFC-215 | AgentLoop Persistence | Dependencies |
| RFC-218 | Checkpoint Tree | Dependencies |
| RFC-219 | Goal Completion Module | Dependencies |
| RFC-201 | AgentLoop Plan-Execute | Supersedes loop driver |
| RFC-203 | AgentLoop State & Memory | Related |
| RFC-207 | Thread Management | Related |
| RFC-211 | Tool Result Optimization | Related |
| RFC-213 | Reasoning Quality | Related |
| RFC-214 | Message Ledger | Related |
| RFC-216 | Multi-Thread Lifecycle | Related |
| RFC-217 | Goal Context Management | Related |
| RFC-201 | Layer 2 responsibilities | Supersedes note |
| RFC-200 | Layer 3 | Architecture position |
| RFC-100 | Layer 1 | Architecture position |
| RFC-215 | Persistence layout | Files on disk |
| RFC-218 | Checkpoint anchors | Iteration start node |
| RFC-604 | StatusAssessment | Plan assess node |
| RFC-604 | PlanGeneration | Plan generate node |
| RFC-219 | Goal completion | Goal completion node |
| RFC-614 | Streaming | Stream chunks |

### Markdown Links (References Section)
```markdown
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-100: CoreAgent Runtime
- RFC-604: Plan Phase Robustness
- RFC-215: AgentLoop Persistence Backend
- RFC-218: Checkpoint Tree Architecture
- RFC-219: Goal Completion Module
```

---

## RFC-221: Loop Runner Protocol

### Internal RFC Links
| Reference | Target | Context |
|-----------|--------|---------|
| RFC-001 | Core Modules Architecture | Dependencies |
| RFC-220 | LangGraph Agent Loop | Dependencies |
| RFC-450 | Daemon Communication | Dependencies |
| RFC-452 | Unified Thread Management | Dependencies |

### Markdown Links (References Section)
```markdown
- RFC-001: Core Modules Architecture
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-450: Daemon Communication Protocol
- RFC-452: Unified Thread Management
```

---

## Cross-RFC Reference Summary

### Most Referenced RFCs (within 000-299)
| RFC | Reference Count | Referenced By |
|-----|-----------------|---------------|
| RFC-201 | 20+ | RFC-200, RFC-203, RFC-204, RFC-207, RFC-211, RFC-213, RFC-217, RFC-219, RFC-220, RFC-221 |
| RFC-200 | 15+ | RFC-201, RFC-204, RFC-206, RFC-211, RFC-213, RFC-216, RFC-217 |
| RFC-203 | 10+ | RFC-204, RFC-207, RFC-211, RFC-213, RFC-214, RFC-216, RFC-217 |
| RFC-207 | 10+ | RFC-100, RFC-104, RFC-203, RFC-211, RFC-213, RFC-214 |
| RFC-216 | 10+ | RFC-207, RFC-215, RFC-217, RFC-218 |
| RFC-100 | 10+ | RFC-101, RFC-104, RFC-206, RFC-203, RFC-211, RFC-220 |
| RFC-214 | 8+ | RFC-104, RFC-206, RFC-207, RFC-213, RFC-215, RFC-220 |
| RFC-000 | 8+ | RFC-001, RFC-100, RFC-200, RFC-220, RFC-221 |
| RFC-001 | 8+ | RFC-100, RFC-102, RFC-200, RFC-220, RFC-221 |
| RFC-400 | 7+ | RFC-001, RFC-101, RFC-201, RFC-203 |

### Markdown Link Targets (Relative Paths)
| Source RFC | Target File | Target RFC |
|------------|-------------|------------|
| RFC-000 | ./RFC-200-autonomous-goal-management.md | RFC-200 |
| RFC-000 | ./RFC-201-agentloop-plan-execute-loop.md | RFC-201 |
| RFC-000 | ./RFC-400-context-protocol-architecture.md | RFC-400 |
| RFC-000 | ./RFC-408-durability-protocol-architecture.md | RFC-408 |
| RFC-001 | ./RFC-400-context-protocol-architecture.md | RFC-400 |
| RFC-001 | ./RFC-402-memory-protocol-architecture.md | RFC-402 |
| RFC-001 | ./RFC-404-planner-protocol-architecture.md | RFC-404 |
| RFC-001 | ./RFC-406-policy-protocol-architecture.md | RFC-406 |
| RFC-001 | ./RFC-408-durability-protocol-architecture.md | RFC-408 |
| RFC-200 | ./RFC-000-system-conceptual-design.md | RFC-000 |
| RFC-200 | ./RFC-001-core-modules-architecture.md | RFC-001 |
| RFC-200 | ./RFC-201-agentloop-plan-execute-loop.md | RFC-201 |
| RFC-204 | ./RFC-200-autonomous-goal-management.md | RFC-200 |
| RFC-204 | ./RFC-201-agentloop-plan-execute-loop.md | RFC-201 |
| RFC-204 | ./RFC-450-daemon-communication-protocol.md | RFC-450 |
| RFC-204 | ./RFC-500-cli-tui-architecture.md | RFC-500 |
| RFC-216 | ./RFC-203-agentloop-state-memory.md | RFC-203 |
| RFC-217 | ./RFC-200-autonomous-goal-management.md | RFC-200 |
| RFC-217 | ./RFC-216-agentloop-multithread-lifecycle.md | RFC-216 |
| RFC-217 | ./RFC-203-agentloop-state-memory.md | RFC-203 |
| RFC-218 | ./RFC-216-agentloop-multithread-lifecycle.md | RFC-216 |
| RFC-218 | ./RFC-215-agentloop-persistence-backend.md | RFC-215 |
| RFC-218 | ./RFC-411-event-stream-replay.md | RFC-411 |
| RFC-221 | ./RFC-001-core-modules-architecture.md | RFC-001 |
| RFC-221 | ./RFC-220-langgraph-agent-loop-orchestrator.md | RFC-220 |
| RFC-221 | ./RFC-450-daemon-communication-protocol.md | RFC-450 |
| RFC-221 | ./RFC-452-unified-thread-management.md | RFC-452 |

---

## External References (Outside RFC Range)

### Implementation Guides (IG-xxx)
- IG-372: Prompt split for two-phase Plan
- IG-329: Trimmed plan-generate schema
- IG-150: Planner consolidation
- IG-184: ContextRetrievalModule enhancement
- IG-143: Reasoning quality
- IG-376: Goal progress as assess-model output
- IG-238: Checkpoint Unified Integration
- IG-199: Adaptive final user response
- IG-295: Synthesis policy
- IG-296: Summary policy
- IG-355: Delegate finals
- IG-400: Completion strategy
- IG-317: Output streaming
- IG-304: Execute-phase suppression
- IG-343: Headless mode
- IG-402: Step card rendering
- IG-339: Subagent allowlist
- IG-258: Priority-aware overflow
- IG-183: SOOTHE_ prefix removal
- IG-174: CLI Import Violations Fix
- IG-175: WebSocket Migration
- IG-119: Suppression rules

### Deprecated/Superseded RFCs
- RFC-0011: Dynamic Goal Management (superseded by RFC-200)
- RFC-0016: Tool Interface Optimization (superseded by RFC-101)
- RFC-0025: Tool Event Naming (superseded by RFC-101)
- RFC-0015: Progress Event Protocol (superseded by RFC-401)
- RFC-0019: Unified Event Processing (superseded by RFC-401)
- RFC-0022: Daemon-side Filtering (superseded by RFC-401)
- RFC-0020: Event Display Architecture (superseded by RFC-501)
- RFC-0024: Verbosity Tier Unification (superseded by RFC-501)
- RFC-0004: Research Agent (superseded by RFC-601)
- RFC-0005: Browser Agent (superseded by RFC-601)
- RFC-0021: Code Weaver (superseded by RFC-601)
- RFC-0008: Layer 2 Agentic Loop (superseded by RFC-201)
- RFC-605: Explore Subagent (partially superseded by RFC-613)

---

*Extracted: 2026-05-13*
*Range: RFC-000 through RFC-299*
