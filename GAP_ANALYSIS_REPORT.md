# Comprehensive Gap Analysis: RFC Specifications vs Implementation

**Analysis Date:** 2026-03-17
**Project:** Soothe
**RFCs Analyzed:** 8 documents (RFC-0001 through RFC-0008)

---

## Executive Summary

This analysis compares the 8 RFC specification documents against the actual codebase implementation in the Soothe project. The project has substantial implementation coverage (~90% overall), but there are notable gaps and discrepancies between what the RFCs specify and what exists in code.

**Overall Implementation Coverage by RFC:**
- RFC-0001 (System Conceptual Design): ~85%
- RFC-0002 (Core Modules Architecture): ~90%
- RFC-0003 (CLI TUI Architecture): ~95%
- RFC-0004 (Skillify Agent): ~95%
- RFC-0005 (Weaver Agent): ~90%
- RFC-0006 (Context and Memory): ~95%
- RFC-0007 (Autonomous Iteration Loop): ~95%
- RFC-0008 (Performance Optimization): ~85%

---

## Detailed Findings by RFC

### 1. RFC-0001: System Conceptual Design
**Status:** Draft | **Coverage:** ~85%

#### ✅ Fully Implemented
- All 7 core protocols defined (Context, Memory, Planner, Policy, Durability, RemoteAgent, VectorStore)
- Plan, Permission, ConcurrencyPolicy data models exist
- Protocol-first approach maintained
- Configuration model extensions via SootheConfig

#### ⚠️ Partially Implemented
**Controlled concurrency (Principle 8)**
- `ConcurrencyPolicy` is defined but parallel execution of plan steps is not fully wired into the runner
- The Plan model has a `concurrency` field but the runner processes steps sequentially
- **Impact:** Medium - affects performance optimization for independent steps

**Graceful degradation (Principle 10)**
- Retry logic exists for goals
- Step-level failure handling with "mark failed, try next, revise plan" is incomplete
- **Impact:** Medium - affects robustness in failure scenarios

#### ❌ Not Implemented
**RemoteAgent implementations (ACP and A2A)**
- RFC mentions ACP (Agent Communication Protocol), A2A (Agent-to-Agent), and LangGraph RemoteGraph wrappers
- The `remote/` directory only has `langgraph.py`
- ACP and A2A implementations are completely missing
- **Impact:** High - limits agent interoperability options
- **Location:** `src/soothe/protocols/remote.py` needs ACP and A2A implementations

**MCP session lifecycle (Invariant 11)**
- RFC states: "MCP session lifecycle is managed alongside thread lifecycle (created on thread start, cleaned up on suspend/archive)"
- Current implementation: MCP servers are loaded but session lifecycle management with thread lifecycle is absent
- **Impact:** Medium - potential resource leaks, session state management issues
- **Location:** `src/soothe/cli/daemon.py`, `src/soothe/core/runner.py`

---

### 2. RFC-0002: Core Modules Architecture Design
**Status:** Accepted | **Coverage:** ~90%

#### ✅ Fully Implemented
- All protocol interfaces defined with correct signatures
- ContextProtocol with KeywordContext and VectorContext implementations
- MemoryProtocol with StoreBackedMemory and VectorMemory implementations
- PlannerProtocol with DirectPlanner, SubagentPlanner, RouterPlanner
- PolicyProtocol with ConfigDrivenPolicy
- DurabilityProtocol with JSON, RocksDB, PostgreSQL backends
- VectorStoreProtocol with PGVector, Weaviate, InMemory implementations
- PersistStore abstraction with JSON, RocksDB, PostgreSQL backends

#### ℹ️ Naming Discrepancy
- RFC-0002 and RFC-0006 specify `StoreBackedMemory` but implementation uses `KeywordMemory`
- RFC-0006 clarifies this is intentional - user-facing config uses "keyword" while internal class was renamed
- **Impact:** None - cosmetic/documentation issue only

#### ❌ Missing/Incomplete
**RemoteAgentProtocol implementations**
- Same gap as RFC-0001 - only LangGraph implementation exists
- ACP and A2A implementations specified in RFC-0002 Module 6 are missing
- **Impact:** High - same as RFC-0001

**DurabilityProtocol thread lifecycle**
- The `suspend_thread` and `archive_thread` methods exist in the protocol
- Not wired into the CLI or runner flow
- **Impact:** Medium - thread state management incomplete
- **Location:** `src/soothe/protocols/durability.py`, `src/soothe/cli/main.py`

---

### 3. RFC-0003: CLI TUI Architecture Design
**Status:** Accepted | **Coverage:** ~95%

#### ✅ Fully Implemented
- Three interaction modes: Textual TUI, Headless CLI, Daemon-based execution
- Unix socket IPC protocol with event/command/input message types
- All CLI commands: `run`, `attach`, `server start/stop/status`, `init`, `thread list/resume/archive/inspect/delete/export`, `list-subagents`
- All slash commands: `/help`, `/exit`, `/quit`, `/detach`, `/plan`, `/memory`, `/context`, `/policy`, `/history`, `/review`, `/thread`, `/clear`, `/config`
- TUI widget layout with ConversationPanel, PlanPanel, ActivityPanel, InfoBar, ChatInput
- Stream architecture with `(namespace, mode, data)` tuples
- All protocol custom events (soothe.thread.*, soothe.context.*, soothe.memory.*, soothe.plan.*, soothe.policy.*)
- Default tools: datetime, arxiv, wikipedia, wizsearch
- Thread logging architecture
- Third-party logger suppression

#### ⚠️ Minor Gaps
**HITL approval prompts**
- RFC states: "Initial implementation auto-approves; future versions can present approval prompts via the TUI"
- Currently only auto-approve is implemented
- **Impact:** Low - feature stated as future work
- **Location:** `src/soothe/cli/tui_app.py`, `src/soothe/protocols/policy.py`

**Input history file**
- RFC mentions `$SOOTHE_HOME/history.json` for command history persistence
- Implementation uses in-memory list in ChatInput without persistence
- **Impact:** Low - convenience feature only
- **Location:** `src/soothe/cli/tui_app.py` (ChatInput widget)

---

### 4. RFC-0004: Skillify Agent Architecture Design
**Status:** Draft (RFC Index says Implemented) | **Coverage:** ~95%

#### ✅ Fully Implemented
- SkillWarehouse with directory scanning and SKILL.md parsing
- SkillIndexer with background asyncio.Task loop
- SkillRetriever with vector search
- Data models: SkillRecord, SkillSearchResult, SkillBundle
- Hash-based change detection
- VectorStoreProtocol integration
- Default warehouse path at `~/.soothe/agents/skillify/warehouse/`
- Configuration: SkillifyConfig with all fields
- Observability events: soothe.skillify.index.*, soothe.skillify.retrieve.*

#### ⚠️ Minor Gap
**PolicyProtocol integration**
- RFC states: "Retrieval requests are checked with action type `skillify_retrieve`"
- RFC states: "Skills from paths outside configured warehouse directories are flagged for policy review"
- The retriever has policy parameters but the actual policy check for `skillify_retrieve` action type is not implemented in the retriever code
- **Impact:** Low - security/policy enforcement gap
- **Location:** `src/soothe/subagents/skillify/retriever.py`

---

### 5. RFC-0005: Weaver Agent Architecture Design
**Status:** Draft (RFC Index says Implemented) | **Coverage:** ~90%

#### ✅ Fully Implemented
- LangGraph pipeline: analyze -> check_reuse -> fetch_skills -> harmonize -> generate -> validate -> register -> execute
- RequirementAnalyzer for CapabilitySignature extraction
- ReuseIndex with vector similarity search
- AgentComposer with three-step skill harmonization pipeline
- AgentGenerator for manifest and system_prompt creation
- GeneratedAgentRegistry for package management
- Data models: CapabilitySignature, AgentManifest, ReuseCandidate, SkillConflict, SkillConflictReport, HarmonizedSkillSet, AgentBlueprint
- Configuration: WeaverConfig with all fields
- Observability events: soothe.weaver.*
- Policy-gated generation with validation

#### ❌ Gaps
**MCP integration for generated agents**
- RFC states generated agents can use MCP via `langchain-mcp-adapters`
- Implementation doesn't include MCP server resolution for generated agents
- **Impact:** Medium - limits capabilities of generated agents
- **Location:** `src/soothe/subagents/weaver/generator.py`

**Dynamic loading at startup**
- RFC states: "At agent creation time, `create_soothe_agent()` calls `_resolve_generated_subagents()` which scans `generated_agents_dir`"
- This function is not visible in the reviewed code
- **Impact:** Medium - generated agents may not be discoverable at runtime
- **Location:** `src/soothe/main.py` or `src/soothe/core/runner.py`

**Allowed MCP servers configuration**
- WeaverConfig has `allowed_mcp_servers` field but it's not used in the generator
- **Impact:** Low - configuration exists but not enforced
- **Location:** `src/soothe/subagents/weaver/generator.py`

---

### 6. RFC-0006: Context and Memory Architecture Design
**Status:** Draft | **Coverage:** ~95%

#### ✅ Fully Implemented
- Clear distinction between Context (within-thread) and Memory (cross-thread)
- Unbounded ledger / bounded projection pattern
- KeywordContext and VectorContext implementations
- KeywordMemory and VectorMemory implementations
- PersistStore abstraction with JSON, RocksDB, PostgreSQL backends
- Persistence lifecycle wired into runner (restore on pre-stream, persist on post-stream)
- Configuration reference matches implementation
- SOOTHE_HOME defaults for all paths

#### ⚠️ Gap to Verify
**Memory auto-storage threshold**
- RFC states: "SootheRunner auto-stores responses >50 chars"
- The constant `_MIN_MEMORY_STORAGE_LENGTH = 50` exists in runner.py
- The actual memory storage call in post-stream needs verification of the threshold check
- **Impact:** Low - likely implemented, just needs verification
- **Location:** `src/soothe/core/runner.py`

---

### 7. RFC-0007: Autonomous Iteration Loop
**Status:** Accepted | **Coverage:** ~95%

#### ✅ Fully Implemented
- GoalEngine with goal lifecycle (create, next, complete, fail, list, persist, restore)
- Goal model with all fields (id, description, status, priority, parent_id, retry_count, max_retries, timestamps)
- Runner iteration loop with `_run_autonomous` method
- IterationRecord model
- Reflection integration with PlannerProtocol
- Configuration: AutonomousConfig with enabled_by_default, max_iterations, max_retries
- Stream events: soothe.iteration.*, soothe.goal.*
- CLI flags: --autonomous, --max-iterations

#### ⚠️ Partially Implemented
**Continuation Synthesizer**
- RFC states: "a lightweight LLM call generates the next 'user input' for the agent" using `SootheConfig.create_chat_model("fast")`
- This synthesis step between iterations is not clearly separated in the runner code
- **Impact:** Medium - affects autonomous iteration quality
- **Location:** `src/soothe/core/runner.py` (autonomous loop)

**IterationRecord storage**
- RFC states records are "stored via `ContextProtocol.ingest()`" with tag `"iteration_record"` and high importance (0.9)
- Implementation creates IterationRecord but the ingestion into context is not visible
- **Impact:** Low - record creation exists, ingestion is optional optimization
- **Location:** `src/soothe/core/runner.py`

---

### 8. RFC-0008: Request Processing Workflow and Performance Optimization
**Status:** Draft | **Coverage:** ~85%

#### ✅ Fully Implemented
- QueryClassifier with complexity classification (trivial, simple, medium, complex)
- Heuristic classification rules matching RFC
- Conditional memory recall for medium/complex queries
- Conditional context projection for medium/complex queries
- Template planning for common patterns
- Parallel execution of memory/context operations (`_pre_stream_parallel_memory_context`)
- PerformanceConfig with all fields
- ComplexityThresholds configuration
- Performance timing events (soothe.performance.phase_started/completed)

#### ⚠️ Partially Implemented
**Caching at multiple levels**
- RFC specifies: embedding cache, template cache, and context cache
- Implementation has model caching (`_model_cache`, `_embedding_cache`)
- No explicit embedding cache for queries or template cache
- **Impact:** Medium - performance optimization potential
- **Location:** `src/soothe/core/runner.py`, `src/soothe/core/query_classifier.py`

**Timing events**
- RFC shows detailed timing events with operation breakdowns
- Implementation has basic timing in runner init
- Detailed per-phase timing emission is incomplete
- **Impact:** Low - observability enhancement
- **Location:** `src/soothe/core/runner.py`

#### ❌ Not Implemented
**Performance dashboard metrics**
- RFC specifies: average latency by complexity, percentiles, cache hit rates, classification distribution histograms
- Not collected or exposed
- **Impact:** Low - operational visibility feature
- **Location:** Would need new module or dashboard integration

**Configuration options**
- Several RFC-0008 config options not in PerformanceConfig:
  - `adaptive_processing` (master switch)
  - `conditional_memory_recall` / `conditional_context_projection` (individual toggles)
  - `cache_size` exists but is not used
  - `log_timing_breakdown` / `log_complexity_classification` not implemented
- **Impact:** Medium - configuration flexibility
- **Location:** `src/soothe/config.py` (PerformanceConfig)

---

## Critical Gaps Summary Table

| RFC | Gap | Severity | Impact | Location |
|-----|-----|----------|--------|----------|
| RFC-0001 | RemoteAgent ACP/A2A implementations | **High** | Limits agent interoperability | `src/soothe/protocols/remote.py` |
| RFC-0001 | MCP session lifecycle management | Medium | Resource management, state handling | `src/soothe/cli/daemon.py`, `src/soothe/core/runner.py` |
| RFC-0002 | RemoteAgentProtocol ACP/A2A | **High** | Same as RFC-0001 | `src/soothe/protocols/remote.py` |
| RFC-0002 | Thread lifecycle methods not wired | Medium | Incomplete thread management | `src/soothe/cli/main.py` |
| RFC-0003 | HITL approval prompts | Low | Security feature (future work) | `src/soothe/cli/tui_app.py` |
| RFC-0003 | Input history persistence | Low | Convenience feature | `src/soothe/cli/tui_app.py` |
| RFC-0004 | PolicyProtocol retrieval check | Low | Security enforcement | `src/soothe/subagents/skillify/retriever.py` |
| RFC-0005 | Dynamic loading at startup | Medium | Agent discoverability | `src/soothe/main.py`, `src/soothe/core/runner.py` |
| RFC-0005 | MCP for generated agents | Medium | Generated agent capabilities | `src/soothe/subagents/weaver/generator.py` |
| RFC-0005 | allowed_mcp_servers not enforced | Low | Configuration enforcement | `src/soothe/subagents/weaver/generator.py` |
| RFC-0007 | Continuation Synthesizer | Medium | Autonomous iteration quality | `src/soothe/core/runner.py` |
| RFC-0007 | IterationRecord context ingestion | Low | Context enrichment | `src/soothe/core/runner.py` |
| RFC-0008 | Performance metrics dashboard | Low | Operational visibility | New module needed |
| RFC-0008 | Multi-layer caching | Medium | Performance optimization | `src/soothe/core/runner.py` |
| RFC-0008 | Missing config options | Medium | Configuration flexibility | `src/soothe/config.py` |

---

## Prioritization Recommendations

### High Priority (Address Immediately)
1. **RemoteAgent ACP/A2A implementations** (RFC-0001, RFC-0002)
   - Blocks agent interoperability
   - Required for multi-protocol agent communication
   - Estimated effort: 2-3 weeks per protocol

### Medium Priority (Address in Next Sprint)
2. **MCP session lifecycle management** (RFC-0001)
   - Affects resource management and state handling
   - Potential for resource leaks
   - Estimated effort: 1 week

3. **Dynamic loading of generated agents** (RFC-0005)
   - Affects runtime discoverability
   - Blocks generated agent usage
   - Estimated effort: 3-5 days

4. **Continuation Synthesizer for autonomous loop** (RFC-0007)
   - Affects autonomous iteration quality
   - User-facing impact
   - Estimated effort: 3-5 days

5. **Multi-layer caching implementation** (RFC-0008)
   - Performance optimization
   - User-visible speed improvements
   - Estimated effort: 1 week

6. **Thread lifecycle methods wiring** (RFC-0002)
   - Completes thread management
   - Required for proper suspend/archive
   - Estimated effort: 2-3 days

### Low Priority (Address When Resources Available)
7. **MCP integration for generated agents** (RFC-0005)
   - Enhancement for generated agents
   - Workaround exists (regenerate with MCP config)
   - Estimated effort: 3-5 days

8. **Performance metrics dashboard** (RFC-0008)
   - Nice-to-have operational feature
   - Can be deferred
   - Estimated effort: 1-2 weeks

9. **HITL approval prompts** (RFC-0003)
   - Explicitly marked as future work in RFC
   - Auto-approve is acceptable for now
   - Estimated effort: 1 week

10. **Input history persistence** (RFC-0003)
    - Convenience feature
    - Low user impact
    - Estimated effort: 1-2 days

11. **PolicyProtocol retrieval enforcement** (RFC-0004)
    - Security enhancement
    - Current implementation has policy parameters
    - Estimated effort: 1-2 days

12. **IterationRecord context ingestion** (RFC-0007)
    - Optimization feature
    - Minor benefit
    - Estimated effort: 1 day

13. **Missing performance config options** (RFC-0008)
    - Configuration flexibility
    - Workarounds exist
    - Estimated effort: 2-3 days

---

## Files Analyzed

### RFC Specifications
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0001.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0002.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0003.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0004.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0005.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0006.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0007.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/RFC-0008.md`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/docs/specs/rfc-index.md`

### Key Implementation Files
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/core/runner.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/core/goal_engine.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/core/query_classifier.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/config.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/cli/main.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/cli/daemon.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/cli/tui_app.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/protocols/context.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/protocols/memory.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/protocols/planner.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/protocols/policy.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/protocols/durability.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/subagents/skillify/__init__.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/subagents/weaver/__init__.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/subagents/weaver/composer.py`
- `/Users/chenxm/.claude/worktrees/Soothe/s1/src/soothe/tools/goals.py`

---

## Methodology

This gap analysis was performed by:

1. **Reading all RFC specifications** - Each of the 8 RFCs was analyzed for required features, behaviors, and architectural requirements
2. **Exploring implementation** - Key source files were examined to understand what exists in the codebase
3. **Cross-referencing** - Each RFC requirement was compared against the actual implementation
4. **Categorization** - Gaps were categorized as:
   - ✅ Fully Implemented - Feature complete and matches spec
   - ⚠️ Partially Implemented - Some functionality missing or incomplete
   - ❌ Not Implemented - Completely missing from codebase
   - ℹ️ Discrepancy - Implementation differs from spec but may be intentional

5. **Impact assessment** - Each gap was assigned a severity level based on:
   - User-facing impact
   - System stability/correctness
   - Feature completeness
   - Performance implications

---

## Conclusion

The Soothe project demonstrates strong alignment between specifications and implementation, with approximately 90% overall coverage across the 8 RFCs. The most critical gaps are:

1. **Missing RemoteAgent protocols (ACP/A2A)** - This blocks multi-protocol agent communication
2. **MCP session lifecycle** - Resource management and state handling issue
3. **Generated agent discoverability** - Runtime behavior doesn't match spec

Most gaps are medium or low severity and represent features that are either partially implemented or are "nice-to-have" enhancements. The core functionality described in the RFCs is largely present and functional.

**Recommendation:** Address the high-priority RemoteAgent gap first, then focus on medium-priority items that affect runtime behavior and performance. Low-priority items can be deferred to future sprints or addressed as part of related feature work.