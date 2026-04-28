# soothe.core

Framework orchestration layer — protocol-orchestrated agent runtime.
No transport or UI dependencies.

---

## Layer diagram

```
┌─────────────────────────────────────────────────────┐
│  soothe.ux  (CLI, TUI)                              │
│  soothe.daemon  (process, transports, IPC)          │
└──────────────────────┬──────────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────────┐
│  soothe.core  (this package)                        │
│                                                     │
│  agent/        CoreAgent (deepagents)              │
│  runner/       AgentLoop Orchestration             │
│  thread/       Thread lifecycle, execution, rate    │
│  events/       Event system (constants, models)    │
│  workspace/    Workspace resolution & backends     │
│  context/      Tool context & model override       │
│  scheduling/   Concurrency & step scheduling       │
│  persistence/  Artifact store & policy             │
│  middleware/   5-middleware stack around CoreAgent │
│  resolver/     Checkpointer, durability, tool wire │
│  prompts/      System prompt building              │
│  event_replay/ Event replay & reconstruction       │
└──────────────────────┬──────────────────────────────┘
                       │ uses
┌──────────────────────▼──────────────────────────────┐
│  soothe.protocols   (abstract protocol interfaces)  │
│  soothe.backends    (protocol implementations)      │
│  soothe.cognition   (goal engine)                   │
│  soothe.config      (SootheConfig)                  │
│  soothe.logging     (shared logging primitives)     │
│  deepagents / langchain / langgraph                 │
└─────────────────────────────────────────────────────┘
```

---

## Directory map

| Path | Responsibility |
|------|----------------|
| `agent/` | `CoreAgent` wraps `create_deep_agent()`. Owns the deepagents/langgraph boundary. 5 Soothe-specific middlewares injected here. |
| `runner/` | `AgentLoop` orchestration — protocol pre/post processing, agentic loop (RFC-200), autonomous iteration (RFC-200), DAG step execution, checkpointing. Decomposed into mixins (`_runner_*.py`). |
| `thread/` | Thread lifecycle manager, concurrent executor with rate limiting. Used by daemon and runner. |
| `events/` | Event system — centralized event constants, models, registry, and `register_event()` API. Self-contained module following IG-047. |
| `workspace/` | Workspace management — resolution, validation, workspace-aware backends, and `FrameworkFilesystem` singleton. Unified package for all workspace-related functionality. |
| `context/` | Context management — tool context registry, trigger registry for system message injection, and stream model override for per-async-task model swapping. |
| `scheduling/` | Execution scheduling — concurrency control (hierarchical semaphores), DAG-based step scheduler, and tool caching utilities. |
| `persistence/` | Persistence & policy — artifact store for run artifacts, and configuration-driven policy implementation. |
| `middleware/` | `SoothePolicyMiddleware`, `SystemPromptOptimizationMiddleware`, `ExecutionHintsMiddleware`, `WorkspaceContextMiddleware`, `SubagentContextMiddleware`. |
| `resolver/` | Wires protocols from config: checkpointer, durability, goal engine, tools. |
| `prompts/` | System prompt building — `PromptBuilder`, context XML generation, prompt template loading. |
| `event_replay/` | Event replay and state reconstruction utilities. |

---

## Package Structure (IG-276 Refactoring)

Following IG-047 Module Self-Containment pattern, all core functionality is organized into purpose-driven packages:

### `events/` Package
**Purpose:** Centralized event system infrastructure

Contents:
- `constants.py` — All event type string constants (60+ constants)
- `catalog.py` — Event models, registry, `register_event()` API
- `__init__.py` — Re-exports all event constants, models, and registry functions

Example:
```python
from soothe.core.events import THREAD_CREATED, register_event
from soothe.core.events import ThreadCreatedEvent, EventRegistry
```

### `workspace/` Package
**Purpose:** Unified workspace resolution, validation, and backend management

Contents:
- `resolution.py` — Daemon/client workspace validation
- `stream_resolution.py` — Unified stream resolution for runner
- `backend.py` — Workspace-aware backend wrapper
- `framework_filesystem.py` — Singleton filesystem backend
- `__init__.py` — Re-exports all workspace APIs

Example:
```python
from soothe.core.workspace import (
    FrameworkFilesystem,
    resolve_daemon_workspace,
    WorkspaceAwareBackend,
)
```

### `context/` Package
**Purpose:** Tool context and trigger registries for system message injection

Contents:
- `tool_registry.py` — Tool context fragments registry
- `trigger_registry.py` — Tool trigger mappings
- `model_override.py` — Per-async-task model override via ContextVar
- `__init__.py` — Re-exports all context APIs

Example:
```python
from soothe.core.context import ToolContextRegistry, attach_stream_model_override
```

### `scheduling/` Package
**Purpose:** Execution scheduling and concurrency control

Contents:
- `concurrency.py` — Hierarchical semaphore-based concurrency control
- `step_scheduler.py` — DAG-based plan step scheduler
- `tool_cache.py` — LRU-style tool caching utilities
- `__init__.py` — Re-exports all scheduling APIs

Example:
```python
from soothe.core.scheduling import ConcurrencyController, StepScheduler
```

### `persistence/` Package
**Purpose:** Persistence and configuration-driven policy

Contents:
- `artifact_store.py` — Run artifact management
- `config_policy.py` — ConfigDrivenPolicy implementation
- `__init__.py` — Re-exports all persistence APIs

Example:
```python
from soothe.core.persistence import RunArtifactStore, ConfigDrivenPolicy
```

---

## Public API (`soothe.core`)

```python
from soothe.core import CoreAgent           # Core runtime
from soothe.core import SootheRunner        # Agentic orchestration
from soothe.core import create_soothe_agent # Agent factory
from soothe.core import ConfigDrivenPolicy  # Policy implementation
from soothe.core import FrameworkFilesystem # File backend
from soothe.core import resolve_daemon_workspace, validate_client_workspace
from soothe.core import ResolvedWorkspace, resolve_workspace_for_stream
```

All exports are lazy-loaded in `__init__.py` to keep startup fast.

**Backward Compatibility:** All imports continue to work unchanged. The lazy loading facade maintains the same public API while internally routing to the new packages.

---

## Key execution path

```
SootheRunner.astream(user_input)
  → _run_agentic_loop()          # RFC-200 Reason → Act loop
    → pre-stream: context.restore, memory.recall, plan
    → PhasesMixin._stream_agent  # CoreAgent.astream → LangGraph
    → post-stream: context.ingest, memory.remember, checkpoint
```

---

## Boundary rules

| Direction | Rule |
|-----------|------|
| `core` → `protocols` | OK — core wires protocol implementations |
| `core` → `backends` | Only via resolver (`resolver/`) |
| `core` → `config` | OK |
| `core` → `soothe.logging` | OK — shared logging package |
| `core` → `daemon` | **Forbidden** |
| `core` → `ux` | **Forbidden** |
| `daemon` → `core` | OK (daemon composes core) |
| `ux` → `core` | OK (ux displays core output) |

---

## Upstream dependencies

- `deepagents` — `create_deep_agent`, `CompiledStateGraph`, middlewares
- `langgraph` — checkpointer, streaming
- `langchain-core` — base message types, tools
- `soothe.config` — `SootheConfig`
- `soothe.protocols` — 8 abstract protocol interfaces
- `soothe.backends` — protocol implementations (resolved at runtime)
- `soothe.cognition` — `GoalEngine`
- `soothe.logging` — `ThreadLogger`, `set_thread_id`

## Downstream consumers

- `soothe.daemon` — constructs `SootheRunner`, delegates to runner APIs
- `soothe.ux.cli` — constructs `SootheRunner` for headless runs
- `soothe.ux.tui` — constructs `SootheRunner` for interactive sessions
- `tests/` — unit and integration tests

---

## Refactoring History

- **IG-276 (2026-04-28):** Core directory refactoring — organized 15 root files into 5 purpose-driven packages (events, workspace, context, scheduling, persistence) following IG-047 Module Self-Containment pattern. Zero breaking changes through lazy loading facade.

- **IG-047:** Module Self-Containment — established pattern for self-contained modules with events, plugin, and implementation together.