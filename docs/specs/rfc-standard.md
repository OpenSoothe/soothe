# RFC Standard

This document defines the RFC (Request for Comments) process and specification kinds used in this project.

## Spec Kinds

This project recognizes three kinds of RFC specifications:

### 1. Conceptual Design

**Purpose**: Define the vision, principles, taxonomy, and invariants of the system.

**Contains**:
- Design philosophy and guiding principles
- Core abstractions and concepts
- Terminology and definitions
- System invariants and constraints

**Does NOT Contain**:
- Concrete schemas or data models
- API definitions
- Implementation code

### 2. Architecture Design

**Purpose**: Define components, layers, data flow, and architectural constraints.

**Contains**:
- Component responsibilities and relationships
- Layer architecture and boundaries
- Data flow and communication patterns
- Architectural constraints and decisions
- Abstract schemas (without implementation details)

**Does NOT Contain**:
- Concrete API signatures
- Language-specific implementation code
- Algorithm details

### 3. Implementation Interface Design

**Purpose**: Define API contracts, naming conventions, and interface signatures.

**Contains**:
- Type definitions and interfaces
- API contracts and method signatures
- Naming conventions
- Error handling patterns
- Input/output specifications

**Does NOT Contain**:
- Implementation algorithms
- Business logic details

## RFC Lifecycle

RFCs progress through defined states. Each state transition has specific criteria
and affects how the RFC is displayed in the index.

### Lifecycle States

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

### Deprecation Process

1. **Supersession Notice**: Add "Superseded By: RFC-XXX" to deprecated RFC header
2. **Dependency Update**: Update all RFCs that reference the deprecated RFC
3. **Index Update**: Move from active to deprecated section in `rfc-index.md`
4. **Archive Timeline**: After 90 days in Deprecated status, move to `docs/specs/archive/`

### RFC Header Template for Deprecated RFCs

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

## RFC Numbering

- RFCs are numbered sequentially starting from 0001
- RFC-000 is always the system-wide Conceptual Design
- Subsequent RFCs are Architecture Design or Impl Interface Design
- Each RFC depends on all previous RFCs unless explicitly stated otherwise

## Related Documents

- `rfc-index.md` - Index of all RFCs
- `rfc-history.md` - Change history
- `rfc-namings.md` - Terminology reference
- `templates/` - RFC templates
