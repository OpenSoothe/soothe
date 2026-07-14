# IG-097: Autopilot Phase 1 - Core Execution Implementation

**Guide**: IG-097
**Title**: Autopilot Phase 1 - Core Execution
**Status**: Draft
**Kind**: Implementation Guide
**Created**: 2026-04-03
**Implements**: RFC-200 §Layer 2 Delegation, RFC-204 §1.1-1.3, §2.1-2.5, §3.1-3.3
**Dependencies**: RFC-200, RFC-204, RFC-201, RFC-202

## Overview

Implements Phase 1 of Autopilot Mode: the core execution foundation. This guide covers:
1. Extended Goal lifecycle (7 states)
2. Consensus loop with send-back budget
3. Goal file discovery and parsing
4. Channel protocol (file-based)
5. Layer 2 ↔ Layer 3 tool interface

## Implementation Plan

### Module Structure

```
src/soothe/
├── cognition/
│   ├── goal_engine.py          # EXTEND: Goal states, relationships, file I/O
│   ├── criticality_evaluator.py # NEW: MUST goal evaluation
│   └── channel/
│       ├── __init__.py          # NEW: Channel protocol
│       ├── models.py            # ChannelMessage, message types
│       ├── inbox.py             # File-based inbox
│       └── outbox.py            # File-based outbox
├── core/runner/
│   ├── _runner_autonomous.py    # EXTEND: Consensus loop, send-back
│   └── _runner_autopilot.py     # NEW: Dreaming stub, channel integration
├── config.py                    # EXTEND: Autopilot config section
└── core/event_catalog.py        # EXTEND: Autopilot events
```

## Key Design Decisions

### 1. Extended Goal States

Add `validated`, `suspended`, `blocked` to existing `GoalStatus` Literal.
- `validated` — Layer 3 accepted Layer 2 completion, awaiting final report
- `suspended` — Send-back budget exhausted, waiting for fresh context
- `blocked` — External input needed

### 2. Goal Relationships

Add `informs: list[str]` and `conflicts_with: list[str]` to Goal model alongside existing `depends_on`.

### 3. Consensus Loop

Integrate into `_execute_autonomous_goal()` — after Layer 2 returns, evaluate with send-back tracking on Goal model.

### 4. Goal File Discovery

Parse markdown frontmatter (YAML) and body text. Use existing patterns from codebase for markdown parsing.

### 5. Channel Protocol

Simple file-based: read markdown from inbox/, write JSON to outbox/. No complex serialization.

## Testing Strategy

- Unit tests for goal state transitions
- Unit tests for consensus loop logic
- Unit tests for goal file parsing
- Unit tests for channel inbox/outbox
- Integration test for full consensus flow
