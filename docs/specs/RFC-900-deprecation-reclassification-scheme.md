# RFC-900: RFC Deprecation List and Number Segment Reclassification Scheme

**RFC**: 900
**Title**: RFC Deprecation List and Number Segment Reclassification Scheme
**Status**: Proposed
**Kind**: Process Specification
**Created**: 2026-06-16
**Authors**: Soothe Team

## Abstract

This RFC proposes a comprehensive deprecation list and number segment reclassification scheme for the Soothe RFC corpus. It addresses inconsistent deprecation states, proposes a clearer lifecycle model, reorganizes number segments for better semantic grouping, and establishes a formal deprecation process.

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

#### Immediate Deprecation (Superseded)

| RFC | Current Status | Superseded By | Deprecation Reason |
|-----|---------------|---------------|-------------------|
| RFC-200 | Implemented | RFC-222 (control flow), RFC-625 (GoalEngine deleted) | Partially superseded; control flow replaced by autopilot push model, GoalEngine deleted |
| RFC-203 | Draft | RFC-626 | LoopState eliminated, consolidated into ExecutionState |
| RFC-300 | Superseded | RFC-302, RFC-303 | Combined spec split into separate ContextProtocol and MemoryProtocol specs |
| RFC-411 | Deprecated | RFC-413 | Event stream replay replaced by server-owned display card ledger |
| RFC-605 | Superseded | RFC-613 | Fixed wave-based search replaced by LLM-orchestrated iterative search |

#### Partial Deprecation (Update Status)

| RFC | Current Status | New Status | Reason |
|-----|---------------|------------|--------|
| RFC-201 | Implemented | Implemented (Partially Superseded) | §loop driver superseded by RFC-220 |

### 3. Number Segment Reclassification

Current segments have drifted from original semantics. Propose reorganization:

#### Current Segment Issues

| Segment | Current Theme | Issue | Count |
|---------|--------------|-------|-------|
| 0xx | Foundation | Clear, stable | 2 |
| 1xx | Core Agent | Clear, stable | 6 |
| **2xx** | StrangeLoop & Cognition | **Overcrowded, overlapping concerns** | 23 |
| **3xx** | Protocols | **Underutilized, scattered specs** | 2 |
| **4xx** | Daemon & Transport | **Mixed protocols and architecture** | 13 |
| 5xx | CLI & TUI | Clear, stable | 6 |
| **6xx** | Plugin System & Extensions | **Overcrowded, mixed topics** | 23 |
| 7xx | Product & Applications | Clear, new | 1 |

#### Proposed Reclassification

Reorganize RFCs into clearer semantic segments:

```
0xx – Foundation
├─ System design, principles, terminology
└─ RFC-000, RFC-001

1xx – CoreAgent Runtime
├─ Tool interface, security, workspace
├─ Context injection, skill loading
└─ RFC-100, RFC-101, RFC-102, RFC-103, RFC-104, RFC-105

2xx – StrangeLoop Execution
├─ Plan-execute loop, state management
├─ Checkpointing, threading, persistence
├─ [MERGE] Consolidate overlapping cognition RFCs
└─ RFC-201, RFC-203 (deprecated), RFC-204, RFC-206-226, RFC-228

3xx – Protocol Specifications [EXPAND]
├─ Move protocol specs from 4xx here
├─ ContextProtocol (RFC-302 → RFC-300-series?)
├─ MemoryProtocol (RFC-303 → RFC-300-series?)
├─ PlannerProtocol (RFC-304)
├─ PolicyProtocol (RFC-305)
├─ DurabilityProtocol (RFC-306)
└─ Proposal: Reserve 301-349 for protocols

4xx – Daemon & Communication
├─ Event processing, streaming
├─ IPC, channels, MCP
└─ RFC-401, RFC-403, RFC-411 (deprecated), RFC-412, RFC-413, RFC-450, RFC-452, RFC-454

5xx – CLI & TUI
├─ Presentation, display, UX
└─ RFC-500-505

6xx – Agents & Extensions [REORGANIZE]
├─ Plugin system, built-in agents
├─ Move persistence/backend RFCs to new 8xx
├─ Move security RFCs to new 9xx or merge into 1xx
└─ RFC-600-604, RFC-606, RFC-610-626

7xx – Product & Applications
├─ Desktop, mobile, product specs
└─ RFC-700

[NEW] 8xx – Persistence & Backends
├─ SQLite, vector stores, durability
├─ Extract from 6xx
└─ RFC-801, RFC-802

[NEW] 9xx – Security & Policy
├─ Security protocols, permissions
├─ Extract from 6xx and 4xx
└─ RFC-901
```

#### Reclassification Decision Matrix

| RFC | Current Segment | Proposed Segment | Action |
|-----|-----------------|------------------|--------|
| RFC-300 | 3xx Protocols | **Deprecate** | Superseded by RFC-302/402 |
| RFC-302 | 4xx Daemon | 3xx Protocols | Move to protocol segment |
| RFC-303 | 4xx Daemon | 3xx Protocols | Move to protocol segment |
| RFC-304 | 4xx Daemon | 3xx Protocols | Move to protocol segment |
| RFC-305 | 4xx Daemon | 3xx Protocols | Move to protocol segment |
| RFC-306 | 4xx Daemon | 3xx Protocols | Move to protocol segment |
| RFC-801 | 6xx Plugins | 8xx Persistence | Move to new segment |
| RFC-802 | 6xx Plugins | 8xx Persistence | Move to new segment |
| RFC-901 | 6xx Plugins | 9xx Security | Move to new segment |

### 4. Consolidation Opportunities

Identify overlapping RFCs that should be merged:

#### 2xx Consolidation Candidates

| RFC Group | Overlap | Proposed Action |
|-----------|---------|-----------------|
| RFC-213, RFC-214, RFC-217, RFC-225, RFC-226, RFC-227 | StrangeLoop context, reasoning quality, continuity | **Merge into RFC-214** (Unified StrangeLoop Context) |
| RFC-216, RFC-218, RFC-223 | Checkpoint, threading, forking | **Merge into RFC-218** (Checkpoint Architecture) |
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

#### Phase 3: Archive Creation (Week 3)

1. Create `docs/specs/archive/` directory
2. Move deprecated RFCs to archive (after 90-day hold)
3. Create `docs/specs/archive/README.md` explaining archive purpose
4. Update all internal RFC references

#### Phase 4: Consolidation (Weeks 4-6)

1. Create consolidated RFCs (2xx context, 2xx checkpoint, 6xx reasoning, etc.)
2. Mark original RFCs as "Consolidated into RFC-XXX"
3. Update terminology in `rfc-namings.md`
4. Update CLAUDE.md references

### 6. Deprecation Timeline

| Date | Action | RFCs Affected |
|------|--------|---------------|
| 2026-06-16 | Mark as Deprecated | RFC-200, RFC-203, RFC-300, RFC-411, RFC-605 |
| 2026-06-30 | Update status labels | RFC-201 (Partially Superseded) |
| 2026-09-14 | Archive deprecated RFCs | RFC-300, RFC-411, RFC-605 (90 days elapsed) |
| 2026-12-14 | Archive partially superseded | RFC-200, RFC-203 (pending consolidation) |

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
- 301-349: Protocol specifications
- 350-399: Future protocol extensions
- 800-849: Persistence implementations
- 850-899: Future backend extensions
- 900-949: Security specifications
- 950-999: Future security extensions

### 8. Automated Checks

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

| RFC | Current | New | Action Required |
|-----|---------|-----|------------------|
| RFC-302 | 4xx Daemon | 3xx Protocol | Renumber to RFC-3XX (TBD) |
| RFC-303 | 4xx Daemon | 3xx Protocol | Renumber to RFC-3XX (TBD) |
| RFC-304 | 4xx Daemon | 3xx Protocol | Renumber to RFC-3XX (TBD) |
| RFC-305 | 4xx Daemon | 3xx Protocol | Renumber to RFC-3XX (TBD) |
| RFC-306 | 4xx Daemon | 3xx Protocol | Renumber to RFC-3XX (TBD) |
| RFC-801 | 6xx Plugins | 8xx Persistence | Renumber to RFC-8XX (TBD) |
| RFC-802 | 6xx Plugins | 8xx Persistence | Renumber to RFC-8XX (TBD) |
| RFC-901 | 6xx Plugins | 9xx Security | Renumber to RFC-9XX (TBD) |

**Note:** Renumbering RFCs requires updating all references across the codebase. Consider whether the benefits of cleaner numbering outweigh the migration cost. Alternative: Keep numbers, update segment definitions in index.

## Appendix C: Consolidation Opportunities

### High Priority (Overlapping Active RFCs)

1. **RFC-214 (Message Surface) + RFC-217 (Goal Context) + RFC-225 (Loop Continuity)**
   - All deal with StrangeLoop state/context management
   - Propose: Merge into unified RFC-214 "StrangeLoop Context Architecture"

2. **RFC-218 (Checkpoint Tree) + RFC-216 (Multithread Lifecycle) + RFC-223 (Thread Inheritance)**
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
   - May be superseded by RFC-801/612

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