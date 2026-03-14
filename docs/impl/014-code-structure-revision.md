# IG-014: Code Structure Revision for Future Extensibility

**Guide**: 014
**Title**: Code Structure Revision for Future Extensibility
**Status**: Implemented
**Created**: 2026-03-14
**Related**: RFC-0001, RFC-0002

## Overview

Restructures `src/soothe/` to improve discoverability, reduce import depth,
align naming with user-facing concepts, and prepare for future extensibility
(plugins, new backends, multi-model orchestration).

## Changes

### 1. `core/` package -- framework logic without CLI deps

| File | Purpose |
|------|---------|
| `core/__init__.py` | Re-exports `SootheRunner`, `create_soothe_agent` |
| `core/agent.py` | `create_soothe_agent()` factory only |
| `core/resolver.py` | Protocol, subagent, tool resolution (extracted from `agent.py`) |
| `core/runner.py` | `SootheRunner` (moved from `cli/runner.py`) |
| `core/events.py` | Stream event type constants and helper builders |

### 2. `backends/` -- all protocol implementations grouped

| Old Path | New Path |
|----------|----------|
| `context/keyword.py` | `backends/context/keyword.py` |
| `context/vector_context.py` | `backends/context/vector.py` |
| `memory_store/store_backed.py` | `backends/memory/store.py` |
| `memory_store/vector_memory.py` | `backends/memory/vector.py` |
| `planning/direct.py` | `backends/planning/direct.py` |
| `policy/config_driven.py` | `backends/policy/config_driven.py` |
| `durability/in_memory.py` | `backends/durability/in_memory.py` |
| `remote/langgraph_remote.py` | `backends/remote/langgraph.py` |
| `persistence/__init__.py` | `backends/persistence/__init__.py` |
| `persistence/json_store.py` | `backends/persistence/json_store.py` |
| `persistence/rocksdb_store.py` | `backends/persistence/rocksdb_store.py` |
| `vector_store/__init__.py` | `backends/vector_store/__init__.py` |
| `vector_store/in_memory.py` | `backends/vector_store/in_memory.py` |
| `vector_store/pgvector.py` | `backends/vector_store/pgvector.py` |
| `vector_store/weaviate.py` | `backends/vector_store/weaviate.py` |

### 3. Utils renamed

| Old Path | New Path |
|----------|----------|
| `utils/_streaming.py` | `utils/streaming.py` |
| `utils/_progress.py` | `utils/progress.py` |

### 4. Backward-compatible re-exports

All old import paths continue to work via re-exports in the original `__init__.py` files.
No deprecation warnings are added yet -- that is a future phase.

## Migration Notes

- `soothe.agent.create_soothe_agent` still works (re-exports from `core/agent.py`)
- Legacy `soothe.cli.runner.SootheRunner` re-export removed; use `soothe.core.runner.SootheRunner`
- All `soothe.context`, `soothe.memory_store`, etc. paths still work
- Internal code uses new paths; external code can use either
