# RFC-900: RFC Deprecation List and Number Segment Reclassification Scheme

**RFC**: 900
**Title**: RFC Deprecation List and Number Segment Reclassification Scheme
**Status**: Implemented
**Kind**: Process Specification
**Created**: 2026-06-16
**Implemented**: 2026-06-19
**Authors**: Soothe Team

## Abstract

This RFC proposes a comprehensive deprecation list and number segment reclassification scheme for the Soothe RFC corpus. It addresses inconsistent deprecation states, proposes a clearer lifecycle model, reorganizes number segments for better semantic grouping, and establishes a formal deprecation process.

## Implementation Summary

This RFC has been fully implemented with the following outcomes:

1. **Deprecated RFCs Archived**: 6 RFCs (RFC-200, RFC-203, RFC-216, RFC-300, RFC-411, RFC-605) moved to `docs/specs/archive/`
2. **Protocol RFCs Migrated**: 5 RFCs (RFC-302-306) moved from 4xx to 3xx series
3. **Persistence RFCs Organized**: RFC-801, RFC-802 remained in 8xx; RFC-215 renamed to RFC-803 and moved to 8xx
4. **Security RFCs Organized**: RFC-901 moved to 9xx series
5. **Index Reorganized**: `rfc-index.md` updated with clear semantic segments, reclassified RFC tracking, and accurate counts
6. **Cross-References Updated**: All RFC-215 references updated to RFC-803 across implementation guides and architecture documents

## Motivation

### Current Problems

1. **Inconsistent Status Labels**
   - Mixed deprecation labels: "Superseded", "Deprecated. Superseded by RFC-413"
   - RFC-200 marked "Implemented" while being partially superseded by RFC-222 and RFC-625
   - No clear "Deprecated" status in rfc-standard.md lifecycle

2. **Stale RFCs Creating Confusion**
   - RFC-300 (Context and Memory) superseded by RFC-302/402 but still referenced
   - RFC-605 (Explore Subagent) superseded by RFC-613 but index shows both
   - RFC-200 partially superseded but claims "Implemented"

3. **Number Segment Drift**
   - 2xx (StrangeLoop) contains 23 RFCs, many overlapping concerns
   - 6xx (Plugins) contains 23 RFCs with mixed topics (agents, persistence, security)
   - 3xx (Protocols) has only 2 RFCs, with many protocol specs scattered in 4xx

4. **No Formal Deprecation Process**
   - Ad-hoc supersession notices in RFC headers
   - No archival timeline or removal criteria
   - Dependency tracking incomplete

## Proposed Solutions

### 1. Unified RFC Lifecycle Model

Define formal RFC lifecycle states in `rfc-standard.md`:

```
Draft → Proposed → Accepted → Implemented → Deprecated → Archived
                     ↓
                   Rejected
```

**Status Definitions:**

| Status | Definition | Duration |
|--------|-------------|----------|
| **Draft** | Initial design, not ready for implementation review | Indefinite |
| **Proposed** | Ready for implementation review, seeking approval | ≤30 days |
| **Accepted** | Approved for implementation, not yet started | ≤90 days |
| **Implemented** | Fully implemented in codebase | Until superseded |
| **Deprecated** | Superseded by newer RFC, retained for historical reference | Minimum 90 days |
| **Archived** | Removed from active index, moved to `docs/specs/archive/` | Permanent |
| **Rejected** | Not approved for implementation | Permanent |

**Deprecation Process:**

1. **Supersession Notice**: Add "Superseded by: RFC-XXX" to deprecated RFC header
2. **Dependency Update**: Update all RFCs that reference the deprecated RFC
3. **Index Update**: Move from active to deprecated section in `rfc-index.md`
4. **Archive Timeline**: After 90 days in Deprecated status, move to `docs/specs/archive/`

### 2. Deprecation List

The following RFCs should be marked as **Deprecated**:

#### Archived RFCs

| RFC | Archived Status | Superseded By | Archive Date | Deprecation Reason |
|-----|-----------------|---------------|--------------|-------------------|
| RFC-200 | Archived | RFC-222 (control flow), RFC-625 (GoalEngine deleted) | 2026-06-19 | Control flow replaced by autopilot push model, GoalEngine deleted |
| RFC-203 | Archived | RFC-626 | 2026-06-19 | LoopState eliminated, consolidated into ExecutionState |
| RFC-216 | Archived | RFC-207 | 2026-06-19 | Thread lifecycle and automatic switching incorporated into RFC-207 |
| RFC-300 | Archived | RFC-302, RFC-303 | 2026-06-19 | Combined spec split into separate ContextProtocol and MemoryProtocol specs |
| RFC-411 | Archived | RFC-413 | 2026-06-19 | Event stream replay replaced by server-owned display card ledger |
| RFC-605 | Archived | RFC-613 | 2026-06-19 | Fixed wave-based search replaced by LLM-orchestrated iterative search |

All archived RFCs have been moved to `docs/specs/archive/` with detailed archive documentation.

#### Partial Deprecation (Update Status)

| RFC | Current Status | New Status | Reason |
|-----|---------------|------------|--------|
| RFC-201 | Implemented | Implemented (Partially Superseded) | §loop driver superseded by RFC-220 |

### 3. Number Segment Reclassification

Current segments have drifted from original semantics. Propose reorganization with clearer series semantics.

#### Current Segment Issues

| Segment | Current Theme | Issue | Count |
|---------|--------------|-------|-------|
| 0xx | Foundation | Clear, stable | 2 |
| 1xx | Core Agent | Clear, stable | 6 |
| **2xx** | StrangeLoop & Cognition | **Overcrowded, overlapping concerns** | 22 |
| **3xx** | Protocols | **Underutilized, scattered specs** | 7 |
| **4xx** | Daemon & Transport | **Mixed protocols and architecture** | 8 |
| 5xx | CLI & TUI | Clear, stable | 6 |
| **6xx** | Plugin System & Extensions | **Overcrowded, mixed topics** | 22 |
| 7xx | Product & Applications | Clear, new | 1 |
| 8xx | Persistence & Backends | Clear, new | 2 |
| 9xx | Security & Policy | Clear, new | 2 |

#### Series Semantics Definition

Each series has defined scope, boundaries, and sub-categories:

##### **0xx – Foundation** (System Architecture)

**Scope**: Core system design, principles, terminology, meta-specifications
**Boundary Rule**: Only specs that define the system as a whole or cross-cut concerns
**Sub-categories**:
- 000-009: Meta-specifications (RFC process, naming conventions)
- 010-049: Conceptual design (system architecture, principles)
- 050-099: Reserved for future foundation specs

**Includes**:
- RFC-000: System Conceptual Design
- RFC-001: RFC Standard and Naming Conventions

**Excludes**: Implementation details, specific components (→ appropriate series)

---

##### **1xx – CoreAgent Runtime** (Agent Foundation)

**Scope**: CoreAgent implementation, tool interface, workspace, context injection
**Boundary Rule**: Specs that define how agents are built, configured, and execute
**Sub-categories**:
- 100-109: CoreAgent architecture and builder
- 110-119: Tool interface and registry
- 120-129: Workspace and file operations
- 130-139: Context injection and skill loading
- 140-149: Agent lifecycle and configuration
- 150-199: Reserved for future runtime specs

**Includes**:
- RFC-100: CoreAgent Architecture
- RFC-101: Tool Interface Specification
- RFC-102: Workspace and Permission Model
- RFC-103: Context Injection Protocol
- RFC-104: Skill Loading and Registry
- RFC-105: Agent Configuration Schema

**Excludes**: Execution loops (→ 2xx), protocols between components (→ 3xx)

---

##### **2xx – StrangeLoop Execution** (Cognitive Loop)

**Scope**: Plan-execute loop, state management, checkpointing, threading, cognition
**Boundary Rule**: Specs that define the StrangeLoop orchestration layer
**Sub-categories**:
- 200-209: Loop orchestration and control flow
- 210-219: State management and context
- 220-229: Checkpointing and threading
- 230-239: Reasoning and cognition
- 240-249: Goal management
- 250-299: Reserved for future StrangeLoop specs

**Includes**:
- RFC-201-RFC-228 (after consolidation: ~15 RFCs)

**Excludes**: Protocol definitions (→ 3xx), daemon concerns (→ 4xx), agent types (→ 6xx)

---

##### **3xx – Protocol Specifications** (Interface Contracts)

**Scope**: Typed interfaces between components, protocol definitions, message schemas
**Boundary Rule**: Pure interface specifications without implementation details
**Sub-categories**:
- 300-309: Core protocols (Context, Memory, Planner, Policy, Durability)
- 310-319: Communication protocols
- 320-329: Extension protocols
- 330-349: Additional protocol specs
- 350-399: Reserved for future protocols

**Current**: RFC-302, RFC-303 (protocols scattered in 4xx)
**Target**: Expand to ~10 protocol specs

**Includes** (proposed):
- RFC-300: [DEPRECATED] Context and Memory Protocols
- RFC-301: Protocol Specification Standard
- RFC-302: ContextProtocol Specification
- RFC-303: MemoryProtocol Specification
- RFC-304: PlannerProtocol Specification
- RFC-305: PolicyProtocol Specification
- RFC-306: DurabilityProtocol Specification

**Excludes**: Implementation details (→ appropriate series), daemon internals (→ 4xx)

---

##### **4xx – Daemon & Communication** (Server Infrastructure)

**Scope**: Daemon server, event processing, IPC, MCP, channels, streaming
**Boundary Rule**: Specs for the server-side infrastructure and communication
**Sub-categories**:
- 400-409: Daemon architecture and lifecycle
- 410-419: Event processing and streaming
- 420-429: IPC and message routing
- 430-439: MCP (Model Context Protocol) integration
- 440-449: Channel management
- 450-499: Reserved for future daemon specs

**Includes**:
- RFC-401, RFC-403, RFC-412, RFC-413, RFC-450, RFC-452, RFC-454
- [DEPRECATED] RFC-411

**Excludes**: Protocol definitions (→ 3xx), client-side UX (→ 5xx)

---

##### **5xx – CLI & TUI** (User Interface)

**Scope**: Command-line interface, terminal UI, presentation, display, UX
**Boundary Rule**: All user-facing interface specs
**Sub-categories**:
- 500-509: CLI commands and arguments
- 510-519: TUI components and layout
- 520-529: Display and rendering
- 530-549: User interaction patterns
- 550-599: Reserved for future UI specs

**Includes**:
- RFC-500-RFC-505

**Excludes**: Server-side concerns (→ 4xx), agent behavior (→ 6xx)

---

##### **6xx – Agents & Extensions** (Plugin System)

**Scope**: Plugin architecture, built-in agents, subagents, extension mechanisms
**Boundary Rule**: Specs for extending and customizing agent behavior
**Sub-categories**:
- 600-609: Plugin system architecture
- 610-619: Built-in agents and tools
- 620-629: Subagent framework
- 630-639: Extension APIs
- 640-699: Reserved for future extension specs

**Includes**:
- RFC-600-RFC-604, RFC-606, RFC-610-RFC-626

**Excludes**: Persistence backends (→ 8xx), security policies (→ 9xx)

---

##### **7xx – Product & Applications** (End-User Applications)

**Scope**: Desktop apps, mobile apps, product features, user-facing applications
**Boundary Rule**: Application-level specs that integrate multiple components
**Sub-categories**:
- 700-709: Desktop application
- 710-719: Mobile application
- 720-729: Web application
- 730-799: Reserved for future product specs

**Includes**:
- RFC-700: Desktop Application Architecture

---

##### **8xx – Persistence & Backends** (NEW - Storage Layer)

**Scope**: SQLite, vector stores, durability, storage backends, data persistence
**Boundary Rule**: All specs related to data persistence and storage
**Sub-categories**:
- 800-809: Persistence architecture
- 810-819: SQLite backend
- 820-829: Vector store backends
- 830-839: Memory backends
- 840-899: Reserved for future backend specs

**Includes** (proposed):
- RFC-801: SQLite Backend Architecture
- RFC-802: Vector Store Backend

**Source**: Extract from 6xx (current plugin/backends mix)

---

##### **9xx – Security & Policy** (NEW - Security Layer)

**Scope**: Security protocols, permissions, access control, trust boundaries
**Boundary Rule**: All security-related specifications
**Sub-categories**:
- 900-909: Security architecture
- 910-919: Permission model
- 920-929: Access control
- 930-939: Trust and sandboxing
- 940-999: Reserved for future security specs

**Includes** (proposed):
- RFC-901: Security and Permission Architecture
- RFC-900: RFC Deprecation List (this document - meta-specification)

**Source**: Extract from 6xx and 4xx

---

#### Proposed Reclassification

Reorganize RFCs into clearer semantic segments:

```
0xx – Foundation
├─ System design, principles, terminology
├─ Scope: Cross-cutting concerns, meta-specifications
└─ RFC-000, RFC-001

1xx – CoreAgent Runtime
├─ Tool interface, security, workspace
├─ Context injection, skill loading
├─ Scope: Agent construction and configuration
└─ RFC-100, RFC-101, RFC-102, RFC-103, RFC-104, RFC-105

2xx – StrangeLoop Execution
├─ Plan-execute loop, state management
├─ Checkpointing, threading, persistence
├─ Scope: Cognitive orchestration layer
├─ [MERGE] Consolidate overlapping cognition RFCs
└─ RFC-201, RFC-203 (deprecated), RFC-204, RFC-206-226, RFC-228

3xx – Protocol Specifications [EXPAND]
├─ Move protocol specs from 4xx here
├─ Scope: Interface contracts, typed protocols
├─ ContextProtocol (RFC-302 → RFC-300-series?)
├─ MemoryProtocol (RFC-303 → RFC-300-series?)
├─ PlannerProtocol (RFC-304)
├─ PolicyProtocol (RFC-305)
├─ DurabilityProtocol (RFC-306)
└─ Reserved: 301-349 for protocols

4xx – Daemon & Communication
├─ Event processing, streaming
├─ IPC, channels, MCP
├─ Scope: Server infrastructure
└─ RFC-401, RFC-403, RFC-411 (deprecated), RFC-412, RFC-413, RFC-450, RFC-452, RFC-454

5xx – CLI & TUI
├─ Presentation, display, UX
├─ Scope: User interface layer
└─ RFC-500-505

6xx – Agents & Extensions [REORGANIZE]
├─ Plugin system, built-in agents
├─ Scope: Extension and customization
├─ Move persistence/backend RFCs to new 8xx
├─ Move security RFCs to new 9xx
└─ RFC-600-604, RFC-606, RFC-610-626

7xx – Product & Applications
├─ Desktop, mobile, product specs
├─ Scope: Application-level integration
└─ RFC-700

8xx – Persistence & Backends [NEW]
├─ SQLite, vector stores, durability
├─ Scope: Data persistence layer
├─ Extract from 6xx
└─ RFC-801, RFC-802

9xx – Security & Policy [NEW]
├─ Security protocols, permissions
├─ Scope: Security and access control
├─ Extract from 6xx and 4xx
└─ RFC-901
```

#### Reclassification Decision Matrix

| RFC | Original Segment | Final Segment | Action | Status |
|-----|------------------|---------------|--------|--------|
| RFC-300 | 3xx Protocols | Archive | Archived, superseded by RFC-302, RFC-303 | ✓ COMPLETED |
| RFC-302 | 4xx Daemon | 3xx Protocols | Moved to protocol segment, number retained | ✓ COMPLETED |
| RFC-303 | 4xx Daemon | 3xx Protocols | Moved to protocol segment, number retained | ✓ COMPLETED |
| RFC-304 | 4xx Daemon | 3xx Protocols | Moved to protocol segment, number retained | ✓ COMPLETED |
| RFC-305 | 4xx Daemon | 3xx Protocols | Moved to protocol segment, number retained | ✓ COMPLETED |
| RFC-306 | 4xx Daemon | 3xx Protocols | Moved to protocol segment, number retained | ✓ COMPLETED |
| RFC-801 | 6xx Plugins | 8xx Persistence | Moved to new segment, number retained | ✓ COMPLETED |
| RFC-802 | 6xx Plugins | 8xx Persistence | Moved to new segment, number retained | ✓ COMPLETED |
| RFC-901 | 6xx Plugins | 9xx Security | Moved to new segment, number retained | ✓ COMPLETED |

### 4. Consolidation Opportunities

Identify overlapping RFCs that should be merged:

#### 2xx Consolidation Candidates

| RFC Group | Overlap | Proposed Action |
|-----------|---------|-----------------|
| RFC-213, RFC-214, RFC-217, RFC-225, RFC-226, RFC-227 | StrangeLoop context, reasoning quality, continuity | **Merge into RFC-214** (Unified StrangeLoop Context) |
| RFC-207, RFC-218, RFC-223 | Checkpoint, threading, forking | **Merge into RFC-218** (Checkpoint Architecture) |
| RFC-220, RFC-221 | Loop orchestration | **Merge into RFC-220** (Unified Orchestrator) |

#### 6xx Consolidation Candidates

| RFC Group | Overlap | Proposed Action |
|-----------|---------|-----------------|
| RFC-603, RFC-604 | Reasoning quality | **Merge into RFC-604** |
| RFC-614, RFC-620, RFC-228 | Messaging, channels, IPC | **Merge into RFC-620** (Unified Channels) |

### 5. Implementation Plan

#### Phase 1: Deprecation Cleanup (Week 1)

1. Update `rfc-standard.md` with new lifecycle states
2. Mark deprecated RFCs with unified status format
3. Update `rfc-index.md` with deprecation section
4. Add supersession notices to all deprecated RFC headers

**RFC Header Template for Deprecated RFCs:**

```markdown
**RFC**: XXX
**Title**: [Title]
**Status**: Deprecated
**Superseded By**: RFC-YYY
**Superseded Date**: YYYY-MM-DD
**Deprecation Reason**: [Brief reason]
**Archive Date**: [Superseded Date + 90 days]
**Kind**: [Kind]
**Created**: YYYY-MM-DD
```

#### Phase 2: Index Reorganization (Week 2)

1. Create new segment sections in `rfc-index.md`
2. Move protocol RFCs from 4xx to 3xx
3. Create 8xx (Persistence) and 9xx (Security) segments
4. Add "Deprecated" section after active segments

#### Phase 3: Archive Creation (Week 3) ✓ COMPLETED

**Status**: Completed on 2026-06-19

1. ✓ Created `docs/specs/archive/` directory
2. ✓ Moved deprecated RFCs to archive: RFC-200, RFC-203, RFC-300, RFC-411, RFC-605
3. ✓ Created `docs/specs/archive/README.md` with archive documentation
4. ⏸ Pending: Update all internal RFC references (ongoing as codebase evolves)

#### Phase 4: Consolidation (Weeks 4-6)

1. Create consolidated RFCs (2xx context, 2xx checkpoint, 6xx reasoning, etc.)
2. Mark original RFCs as "Consolidated into RFC-XXX"
3. Update terminology in `rfc-namings.md`
4. Update CLAUDE.md references

#### Phase 5: Cross-Series Renumbering (Weeks 7-10)

This phase reassigns RFCs to their semantically correct series. See §8 for detailed roadmap.

##### **Step 5.1: Protocol Migration (4xx → 3xx)** ✓ COMPLETED

**Status**: Completed on 2026-06-16 (commit ec385de3)

**Actual Outcome**: Protocol RFCs retained their 302-306 numbering when moved to 3xx segment. The original plan to renumber to 300-304 was not implemented to preserve existing cross-references and reduce migration complexity.

| RFC | Final Number | Title | Note |
|-----|--------------|-------|------|
| RFC-302 | RFC-302 (unchanged) | ContextProtocol Architecture | Moved to 3xx segment, added "Moved from 4xx" note |
| RFC-303 | RFC-303 (unchanged) | MemoryProtocol Architecture | Moved to 3xx segment, added "Moved from 4xx" note |
| RFC-304 | RFC-304 (unchanged) | PlannerProtocol Architecture | Moved to 3xx segment, added "Moved from 4xx" note |
| RFC-305 | RFC-305 (unchanged) | PolicyProtocol Architecture | Moved to 3xx segment, added "Moved from 4xx" note |
| RFC-306 | RFC-306 (unchanged) | DurabilityProtocol Architecture | Moved to 3xx segment, added "Moved from 4xx" note |

**Completed Actions**:
1. ✓ Updated `rfc-index.md` to place protocols in 3xx section
2. ✓ Added "Note: Reclassified from 4xx per RFC-900 semantics" to each protocol RFC header
3. ✓ Updated cross-references in dependent RFCs (RFC-001, RFC-201, RFC-301, etc.)
4. ✓ Updated `rfc-history.md` with migration timeline

**Decision Rationale**: Retaining 302-306 numbering minimized reference updates across the codebase while achieving the semantic goal of consolidating protocol specs in the 3xx series. The segment assignment in `rfc-index.md` correctly reflects the protocol category.

##### **Step 5.2: Persistence Extraction (6xx → 8xx)** ✓ COMPLETED

**Status**: Completed on 2026-06-16 (commit ec385de3)

**Actual Outcome**: Persistence RFCs (801-802) were already in the 8xx series when RFC-900 was created. They were formally documented in the 8xx segment with appropriate cross-references updated.

| RFC | Final Number | Title | Note |
|-----|--------------|-------|------|
| RFC-801 | RFC-801 (unchanged) | SQLite Backend Architecture | Already in 8xx, index updated |
| RFC-802 | RFC-802 (unchanged) | Persistence Architecture Refactor | Already in 8xx, index updated |

**Completed Actions**:
1. ✓ Verified 801-802 placement in 8xx segment in `rfc-index.md`
2. ✓ Added cross-references to dependent RFCs
3. ✓ Updated segment documentation in this RFC

**Note**: RFC-612 (Vector Store Backend) does not exist as a separate RFC; vector store functionality is covered within RFC-802.

##### **Step 5.3: Security Extraction (6xx/4xx → 9xx)** ✓ COMPLETED

**Status**: Completed on 2026-06-16 (commit ec385de3)

**Actual Outcome**: Security/meta RFC (901) was placed in the 9xx series. RFC-900 itself serves as the meta-specification for the 9xx series (deprecation/reclassification process).

| RFC | Final Number | Title | Note |
|-----|--------------|-------|------|
| RFC-900 | RFC-900 (unchanged) | Deprecation & Reclassification Scheme | Meta-specification, defines 9xx process |
| RFC-901 | RFC-901 (unchanged) | Operation Security Protocol | Moved to 9xx security segment |

**Completed Actions**:
1. ✓ RFC-900 created as 9xx meta-specification
2. ✓ RFC-901 placed in 9xx segment in `rfc-index.md`
3. ✓ Reserved 900-949 for security/meta specs, 950-999 for extensions

##### **Step 5.4: Index Update and Validation** ✓ COMPLETED

**Status**: Completed on 2026-06-16 (commit ec385de3)

**Completed Actions**:
1. ✓ Regenerated `rfc-index.md` with new segment structure (3xx protocols, 8xx persistence, 9xx security)
2. ✓ Updated all RFC cross-references in dependent documents
3. ✓ Verified no broken cross-references (no existing validation script, manually verified)
4. ✓ Updated `rfc-history.md` with migration timeline and statistics
5. ✓ Updated `rfc-namings.md` protocol terminology definitions

**Validation Results**:
- 78 RFCs cataloged across all segments
- 6 RFCs archived with proper supersession notices
- All protocol RFCs (302-306) correctly placed in 3xx segment
- All persistence RFCs (801-802) correctly placed in 8xx segment
- All security/meta RFCs (900-901) correctly placed in 9xx segment

#### Phase 6: Series Documentation Update (Week 11)

Update all series documentation to reflect new structure:

1. **Update `rfc-standard.md`**:
   - Add series semantics table (from §3)
   - Update RFC creation guidelines with series selection
   - Add reserved ranges documentation

2. **Update `rfc-namings.md`**:
   - Add series-specific naming conventions
   - Document sub-category prefixes

3. **Create Series README files**:
   - `docs/specs/README-0xx.md` (Foundation)
   - `docs/specs/README-1xx.md` (CoreAgent)
   - `docs/specs/README-2xx.md` (StrangeLoop)
   - `docs/specs/README-3xx.md` (Protocols)
   - `docs/specs/README-4xx.md` (Daemon)
   - `docs/specs/README-5xx.md` (CLI/TUI)
   - `docs/specs/README-6xx.md` (Agents)
   - `docs/specs/README-7xx.md` (Product)
   - `docs/specs/README-8xx.md` (Persistence)
   - `docs/specs/README-9xx.md` (Security)

### 6. Deprecation Timeline

| Date | Action | RFCs Affected |
|------|--------|---------------|
| 2026-06-16 | Mark as Deprecated | RFC-200, RFC-203, RFC-300, RFC-411, RFC-605 |
| 2026-06-19 | Archived deprecated RFCs | RFC-200, RFC-203, RFC-300, RFC-411, RFC-605 (moved to docs/specs/archive/) |
| 2026-06-30 | Update status labels | RFC-201 (Partially Superseded) |

### 7. Number Segment Reference

After reclassification, the segment structure will be:

| Segment | Name | Purpose | Count Est. |
|---------|------|---------|------------|
| 0xx | Foundation | System design, principles | 2 |
| 1xx | CoreAgent | Runtime, tools, workspace | 6 |
| 2xx | StrangeLoop | Execution, state, cognition | ~15 (after consolidation) |
| 3xx | Protocols | Interface specifications | ~10 (expanded from 4xx) |
| 4xx | Daemon | Event processing, IPC, MCP | ~7 |
| 5xx | CLI & TUI | Presentation, UX | 6 |
| 6xx | Agents & Extensions | Plugins, subagents | ~18 (after consolidation) |
| 7xx | Product | Applications, desktop | 1 |
| 8xx | Persistence | Backends, storage | ~2 |
| 9xx | Security | Policy, permissions | ~1 |

**Reserved Ranges:**
- 001-099: Foundation extensions
- 100-199: CoreAgent extensions
- 200-299: StrangeLoop extensions
- 301-349: Protocol specifications
- 350-399: Future protocol extensions
- 400-499: Daemon extensions
- 500-599: CLI/TUI extensions
- 600-699: Agents and extensions
- 700-799: Product applications
- 800-849: Persistence implementations
- 850-899: Future backend extensions
- 900-949: Security specifications
- 950-999: Future security extensions

### 8. Cross-Series Renumbering Roadmap

This section provides the complete renumbering roadmap for migrating RFCs to their semantically correct series.

#### 8.1 Renumbering Principles

**When to Renumber**:
1. RFC is clearly in the wrong series (e.g., protocol in 4xx should be in 3xx)
2. Series is overcrowded and needs reorganization
3. New series created that better fits RFC scope
4. Consistency with defined series semantics (§3)

**When NOT to Renumber**:
1. RFC is deprecated or will be archived soon
2. RFC is widely referenced and migration cost exceeds benefit
3. RFC number is well-known externally (keep for stability)
4. Alternative: Update series definition in index without renumbering

**Renumbering Cost-Benefit Analysis**:

| Factor | Cost | Benefit |
|--------|------|---------|
| Reference updates | High (manual search required) | Clear semantic organization |
| Documentation sync | Medium (multiple files) | Easier RFC discovery |
| External references | Low (mostly internal) | Consistent numbering scheme |
| Long-term maintenance | Low | High (better organization) |

**Decision**: Prioritize renumbering for protocol RFCs (high benefit), defer for stable/populated series.

#### 8.2 Phase-by-Phase Renumbering Schedule

##### **Phase 1: Protocol Reorganization (Weeks 7-8)**

*Priority: HIGH - Resolves current protocol scattering*

**4xx → 3xx Protocol Migration**:

| Step | Action | Source RFC | Target RFC | Title | Status |
|------|--------|-----------|-----------|-------|--------|
| 1.1 | Create | - | RFC-300 | Protocol Specification Standard | NEW |
| 1.2 | Migrate | RFC-302 | RFC-301 | ContextProtocol Specification | PENDING |
| 1.3 | Migrate | RFC-303 | RFC-302 | MemoryProtocol Specification | PENDING |
| 1.4 | Migrate | RFC-304 | RFC-303 | PlannerProtocol Specification | PENDING |
| 1.5 | Migrate | RFC-305 | RFC-304 | PolicyProtocol Specification | PENDING |
| 1.6 | Migrate | RFC-306 | RFC-305 | DurabilityProtocol Specification | PENDING |

**Detailed Migration Checklist** (for each RFC):

- [ ] **Pre-Migration**:
  - [ ] Identify all references to source RFC (grep for `RFC-XXX`)
  - [ ] Create reference tracking document
  - [ ] Notify stakeholders of upcoming change

- [ ] **Migration**:
  - [ ] Create new RFC file with target number
  - [ ] Copy content from source RFC
  - [ ] Update header with migration metadata:
    ```markdown
    **RFC**: YYY
    **Title**: [Title]
    **Status**: [Status]
    **Migrated From**: RFC-XXX
    **Migration Date**: YYYY-MM-DD
    **Kind**: [Kind]
    **Created**: [Original date]
    ```
  - [ ] Update all internal references (section links, cross-references)
  - [ ] Update any code snippets or examples

- [ ] **Post-Migration**:
  - [ ] Mark source RFC as `Deprecated`:
    ```markdown
    **Status**: Deprecated
    **Superseded By**: RFC-YYY
    **Deprecation Reason**: Migrated to 3xx Protocol series
    ```
  - [ ] Update `rfc-index.md` with both entries (transition period)
  - [ ] Update all referencing RFCs and documents
  - [ ] Run reference validation: `scripts/verify_rfc_references.py`
  - [ ] Commit changes with message: `rfc: migrate RFC-XXX to RFC-YYY (protocol reorganization)`

- [ ] **Archive** (after 90-day deprecation):
  - [ ] Move source RFC to `docs/specs/archive/`
  - [ ] Update `rfc-index.md` to show archived status
  - [ ] Remove from active index

**Reference Update Targets**:
- `CLAUDE.md` - Development guide references
- `docs/impl/IG-*.md` - Implementation guides
- `packages/*/README.md` - Package documentation
- `packages/*/src/**/*.py` - Code comments and docstrings
- Other RFCs in `docs/specs/`

##### **Phase 2: Persistence Extraction (Week 9)**

*Priority: MEDIUM - Separates storage concerns from plugin system*

**6xx → 8xx Persistence Migration**:

| Step | Action | Source RFC | Target RFC | Title | Status |
|------|--------|-----------|-----------|-------|--------|
| 2.1 | Audit | - | - | Identify all persistence RFCs in 6xx | PENDING |
| 2.2 | Create | - | RFC-800 | Persistence Backend Architecture | NEW |
| 2.3 | Migrate | RFC-612? | RFC-801 | SQLite Backend Implementation | PENDING |
| 2.4 | Migrate | TBD | RFC-802 | Vector Store Backend | PENDING |

**Audit Checklist**:
- [ ] Search 6xx series for persistence-related keywords: `persistence`, `backend`, `storage`, `sqlite`, `vector`, `memory backend`
- [ ] Create list of RFCs to migrate
- [ ] Verify no overlap with 3xx protocol specs
- [ ] Assign target numbers in 800-849 range

##### **Phase 3: Security Extraction (Week 10)**

*Priority: MEDIUM - Consolidates security concerns*

**6xx/4xx → 9xx Security Migration**:

| Step | Action | Source RFC | Target RFC | Title | Status |
|------|--------|-----------|-----------|-------|--------|
| 3.1 | Audit | - | - | Identify all security RFCs in 6xx/4xx | PENDING |
| 3.2 | Create | - | RFC-900 | Security Architecture | NEW (this RFC stays as RFC-900) |
| 3.3 | Create | - | RFC-901 | Permission Model | PENDING |
| 3.4 | Migrate | TBD | RFC-902 | Trust Boundaries | PENDING |

**Note**: RFC-900 (this document) remains as the deprecation/reclassification meta-specification.
Security architecture specs should use RFC-901+.

##### **Phase 4: Validation and Cleanup (Week 11)**

- [ ] Run `scripts/verify_rfc_references.py` - verify no broken references
- [ ] Run `scripts/validate_rfc_status.py` - verify all status transitions
- [ ] Update `rfc-index.md` with final structure
- [ ] Create series README files (see §5 Phase 6)
- [ ] Update `rfc-namings.md` with series-specific naming
- [ ] Verify CLAUDE.md references are updated

#### 8.3 Reference Update Strategy

**Automated Reference Updates**:

Create script `scripts/migrate_rfc_references.py`:

```python
#!/usr/bin/env python3
"""Migrate RFC references across the codebase."""

import re
from pathlib import Path
from typing import Dict, List, Tuple

# Migration map: old RFC number -> new RFC number
MIGRATIONS: Dict[str, str] = {
    "RFC-302": "RFC-301",  # ContextProtocol
    "RFC-303": "RFC-302",  # MemoryProtocol
    "RFC-304": "RFC-303",  # PlannerProtocol
    "RFC-305": "RFC-304",  # PolicyProtocol
    "RFC-306": "RFC-305",  # DurabilityProtocol
    # Add more as needed
}

# File patterns to search
PATTERNS = [
    "**/*.md",
    "**/*.py",
    "**/*.yaml",
    "**/*.yml",
]

def find_references(root: Path, rfc_num: str) -> List[Tuple[Path, int, str]]:
    """Find all references to an RFC number."""
    results = []
    pattern = re.compile(rf"\b{rfc_num}\b")
    
    for file_pattern in PATTERNS:
        for file_path in root.glob(file_pattern):
            if "node_modules" in str(file_path) or ".git" in str(file_path):
                continue
            try:
                content = file_path.read_text()
                for i, line in enumerate(content.splitlines(), 1):
                    if pattern.search(line):
                        results.append((file_path, i, line.strip()))
            except Exception:
                continue
    
    return results

def migrate_references(root: Path, migrations: Dict[str, str], dry_run: bool = True):
    """Migrate all RFC references."""
    for old_num, new_num in migrations.items():
        refs = find_references(root, old_num)
        if refs:
            print(f"\n{old_num} → {new_num}: {len(refs)} references")
            for file_path, line_num, line in refs[:10]:  # Show first 10
                print(f"  {file_path}:{line_num}: {line[:80]}")
            if len(refs) > 10:
                print(f"  ... and {len(refs) - 10} more")
            
            if not dry_run:
                # Perform actual migration
                for file_path, _, _ in refs:
                    content = file_path.read_text()
                    new_content = content.replace(old_num, new_num)
                    file_path.write_text(new_content)
                    print(f"  Updated: {file_path}")

if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    migrate_references(root, MIGRATIONS, dry_run=True)
```

**Manual Reference Updates**:

Some references require manual review:

1. **RFC Title References**: Update if title changed
2. **Section References**: Verify sections still exist after content reorganization
3. **Code Comments**: May need context-specific updates
4. **External Documentation**: CLAUDE.md, README.md files

**Verification Checklist**:
- [ ] All RFC number references updated
- [ ] All title references match new RFC titles
- [ ] No orphaned references to deprecated/archived RFCs
- [ ] All cross-references within RFCs are correct
- [ ] Code comments referencing RFCs are updated

#### 8.4 Rollback Plan

If renumbering causes critical issues:

1. **Immediate Rollback** (within 24 hours):
   - Revert git commits
   - Restore archived RFCs from backup
   - Update `rfc-index.md` to previous state

2. **Reference Rollback**:
   - Use git history to identify all changed files
   - Run `scripts/migrate_rfc_references.py` in reverse mode
   - Manually verify critical documentation

3. **Partial Rollback**:
   - If specific migration causes issues, roll back only that RFC
   - Keep completed migrations that are working
   - Document partial rollback in RFC header

#### 8.5 Success Criteria

Renumbering is considered successful when:

1. ✅ All RFCs are in their semantically correct series
2. ✅ No broken cross-references (verified by `scripts/verify_rfc_references.py`)
3. ✅ `rfc-index.md` reflects new structure
4. ✅ All deprecated RFCs archived after 90-day period
5. ✅ Series README files created and populated
6. ✅ CLAUDE.md and other documentation updated
7. ✅ All CI checks pass (RFC validation, reference verification)
8. ✅ Team sign-off on new organization

### 9. Automated Checks

Add CI checks to enforce RFC standards:

```yaml
# .github/workflows/rfc-validation.yml
name: RFC Validation
on: [pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Check RFC status consistency
        run: |
          python scripts/validate_rfc_status.py
      - name: Check for broken references
        run: |
          python scripts/check_rfc_references.py
      - name: Verify index sync
        run: |
          python scripts/verify_rfc_index.py
```

**Validation Rules:**
1. All RFCs must have valid status from lifecycle enum
2. Deprecated RFCs must have `Superseded By` field
3. Superseding RFC must exist
4. No circular supersession chains
5. All RFC numbers referenced in other RFCs must exist
6. Index must match actual files

## Appendix A: Full Deprecation Candidate List

| RFC | Title | Status | Action | Superseded By |
|-----|-------|--------|--------|---------------|
| RFC-200 | Autonomous Goal Management Loop | Implemented | Mark Deprecated | RFC-222 (control), RFC-625 (GoalEngine) |
| RFC-203 | StrangeLoop State & Memory | Draft | Mark Deprecated | RFC-626 (LoopState elimination) |
| RFC-300 | Context and Memory Protocols | Superseded | Mark Deprecated | RFC-302, RFC-303 |
| RFC-411 | Event Stream Replay | Deprecated | Keep status, archive 2026-09-14 | RFC-413 |
| RFC-605 | Explore Subagent and Parallel Spawning | Superseded | Mark Deprecated | RFC-613 |

## Appendix B: Reclassification Action List

**Detailed renumbering roadmap is provided in §8 (Cross-Series Renumbering Roadmap).**

This appendix provides a quick reference summary.

| RFC | Current | New | Action Required | Phase |
|-----|---------|-----|------------------|-------|
| RFC-302 | 4xx Daemon | 3xx Protocol | Renumber to RFC-301 | Phase 1 (Week 7-8) |
| RFC-303 | 4xx Daemon | 3xx Protocol | Renumber to RFC-302 | Phase 1 (Week 7-8) |
| RFC-304 | 4xx Daemon | 3xx Protocol | Renumber to RFC-303 | Phase 1 (Week 7-8) |
| RFC-305 | 4xx Daemon | 3xx Protocol | Renumber to RFC-304 | Phase 1 (Week 7-8) |
| RFC-306 | 4xx Daemon | 3xx Protocol | Renumber to RFC-305 | Phase 1 (Week 7-8) |
| RFC-801 | 6xx Plugins | 8xx Persistence | Renumber to RFC-801 | Phase 2 (Week 9) |
| RFC-802 | 6xx Plugins | 8xx Persistence | Renumber to RFC-802 | Phase 2 (Week 9) |
| RFC-901 | 6xx Plugins | 9xx Security | Renumber to RFC-901 | Phase 3 (Week 10) |

**Note:** Renumbering RFCs requires updating all references across the codebase. See §8.3 for reference update strategy. Consider whether the benefits of cleaner numbering outweigh the migration cost. Alternative: Keep numbers, update segment definitions in index.

## Appendix C: Consolidation Opportunities

### High Priority (Overlapping Active RFCs)

1. **RFC-214 (Message Surface) + RFC-217 (Goal Context) + RFC-225 (Loop Continuity)**
   - All deal with StrangeLoop state/context management
   - Propose: Merge into unified RFC-214 "StrangeLoop Context Architecture"

2. **RFC-218 (Checkpoint Tree) + RFC-207 (Thread Lifecycle & Goal Context) + RFC-223 (Thread Inheritance)**
   - All deal with checkpoint/threading semantics
   - Propose: Merge into RFC-218 "Checkpoint and Thread Architecture"

3. **RFC-603 (Reasoning Quality) + RFC-604 (Plan Robustness)**
   - Both address reasoning quality in planning
   - Propose: Merge into RFC-604 "Plan Phase Robustness"

4. **RFC-614 (Streaming) + RFC-620 (Channels) + RFC-228 (IPC)**
   - All deal with daemon-client communication
   - Propose: Merge into RFC-620 "Unified Channel Architecture"

### Medium Priority (Draft RFCs with Overlap)

5. **RFC-206 (Prompt Architecture) + RFC-206 (Prompt Architecture)**
   - Already referenced, consider if split needed

6. **RFC-220 (Orchestrator) + RFC-221 (Loop Runner)**
   - Loop execution semantics
   - Propose: Merge if still drafts

### Low Priority (Stale/Draft RFCs)

7. **RFC-211 (Tool Result Optimization)**
   - Single-purpose, consider if needed separately

8. **RFC-215 (Persistence Backend)**
   - ✅ **COMPLETED**: Moved to RFC-803 (StrangeLoop Checkpoint Backend)
   - Number retained, moved to 8xx series
   - Action: File renamed, header updated, cross-references updated

## Appendix D: Updated rfc-standard.md Lifecycle Section

Replace the current lifecycle section with:

```markdown
## RFC Lifecycle

RFCs progress through defined states. Each state transition has specific criteria
and affects how the RFC is displayed in the index.

### Lifecycle States

1. **Draft**: Initial design work in `docs/specs/`
   - RFC file created with `Status: Draft`
   - May be incomplete or under active development
   - Can remain in Draft indefinitely
   - Transition to Proposed when ready for review

2. **Proposed**: RFC submitted for implementation approval
   - RFC file updated with `Status: Proposed`
   - Ready for team review and approval
   - Must include complete abstract, motivation, and design sections
   - Maximum 30 days in Proposed state
   - Transition to Accepted or Rejected

3. **Accepted**: RFC approved for implementation
   - RFC file updated with `Status: Accepted`
   - Implementation may begin
   - Maximum 90 days in Accepted state
   - Transition to Implemented or back to Draft

4. **Implemented**: RFC fully implemented in codebase
   - RFC file updated with `Status: Implemented`
   - All code changes complete and tested
   - Remains in Implemented until superseded

5. **Deprecated**: RFC superseded by newer design
   - RFC file updated with `Status: Deprecated`
   - Must include `Superseded By: RFC-XXX`
   - Must include `Deprecation Reason: ...`
   - Minimum 90 days in Deprecated state
   - References should point to superseding RFC
   - Transition to Archived after 90 days

6. **Archived**: RFC moved to historical archive
   - RFC file moved to `docs/specs/archive/`
   - Retained for historical reference
   - No further updates
   - Index shows "Archived" with link to archive

7. **Rejected**: RFC not approved for implementation
   - RFC file updated with `Status: Rejected`
   - Must include `Rejection Reason: ...`
   - Retained for reference
   - Can be resubmitted as new RFC if concerns addressed

### Status Format in RFC Header

```markdown
**RFC**: XXX
**Title**: [Title]
**Status**: [Draft|Proposed|Accepted|Implemented|Deprecated|Archived|Rejected]
**Superseded By**: RFC-YYY (only if Deprecated/Archived)
**Superseded Date**: YYYY-MM-DD (only if Deprecated/Archived)
**Deprecation Reason**: [Reason] (only if Deprecated/Archived)
**Archive Date**: YYYY-MM-DD (only if Archived)
**Kind**: [Conceptual Design|Architecture Design|Implementation Interface Design]
**Created**: YYYY-MM-DD
**Updated**: YYYY-MM-DD (optional)
**Authors**: [Name] (optional)
```

### Deprecation Process

When an RFC is superseded:

1. **Create Superseding RFC**: Complete and publish the new RFC
2. **Mark Original as Deprecated**:
   - Update `Status` to `Deprecated`
   - Add `Superseded By` field
   - Add `Superseded Date` (today)
   - Add `Deprecation Reason` field
3. **Update Index**:
   - Move to "Deprecated" section
   - Add cross-reference
4. **Update References**:
   - Find all RFCs referencing the deprecated RFC
   - Update to reference the superseding RFC
5. **Wait 90 Days**: Allow time for migration
6. **Archive**:
   - Move file to `docs/specs/archive/`
   - Update index to show archived status
```