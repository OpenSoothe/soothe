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

1. **Draft**: Initial design work in `docs/drafts/`
2. **Proposed**: RFC submitted for review
3. **Accepted**: RFC approved for implementation
4. **Implemented**: RFC fully implemented in code
5. **Deprecated**: RFC superseded by newer design

## RFC Numbering

- RFCs are numbered sequentially starting from 0001
- RFC-0001 is always the system-wide Conceptual Design
- Subsequent RFCs are Architecture Design or Impl Interface Design
- Each RFC depends on all previous RFCs unless explicitly stated otherwise

## Related Documents

- `rfc-index.md` - Index of all RFCs
- `rfc-history.md` - Change history
- `rfc-namings.md` - Terminology reference
- `templates/` - RFC templates
