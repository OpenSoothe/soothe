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
│  middleware/   5-middleware stack around CoreAgent  │
│  resolver/     Checkpointer, durability, tool wire  │
│  foundation/   Base types, events, verbosity        │
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
| `middleware/` | `SoothePolicyMiddleware`, `SystemPromptOptimizationMiddleware`, `ExecutionHintsMiddleware`, `WorkspaceContextMiddleware`, `SubagentContextMiddleware`. |
| `resolver/` | Wires protocols from config: checkpointer, durability, goal engine, tools. |
| `foundation/` | Framework-wide base primitives (see below). |
| `workspace.py` | `resolve_daemon_workspace()`, `validate_client_workspace()` — path resolution helpers. |
| `filesystem.py` | `FrameworkFilesystem` — deepagents `BackendProtocol` wrapper for sandboxed file ops. |
| `workspace_aware_backend.py` | Workspace-scoped backend for tool execution. |
| `artifact_store.py` | Run artifact store (attached to `RunnerState`). |
| `concurrency.py` | `ConcurrencyController` — semaphore-based goal/step/LLM limits. |
| `step_scheduler.py` | DAG-based step scheduler for parallel plan execution. |
| `unified_classifier.py` | Fast-model complexity classifier (RFC-0012). |
| `config_driven.py` | `ConfigDrivenPolicy` — policy protocol default implementation. |
| `lazy_tools.py` | Lazy tool group resolver for `soothe_step_tools`. |
| `event_catalog.py` | Event registry, constants, `register_event()`, `custom_event()`. |

---

## foundation/ subpackage

Contains the smallest framework primitives that are imported by every layer.

| Module | Contents |
|--------|----------|
| `base_events.py` | `SootheEvent`, `LifecycleEvent`, `ProtocolEvent`, `SubagentEvent`, `OutputEvent`, `ErrorEvent` |
| `types.py` | `INVALID_WORKSPACE_DIRS` — security constant |
| `verbosity_tier.py` | `VerbosityTier` enum, `should_show()`, `classify_event_to_tier()` |

---

## Public API (`soothe.core`)

```python
from soothe.core import CoreAgent           # Core runtime
from soothe.core import SootheRunner        # Agentic orchestration
from soothe.core import create_soothe_agent # Agent factory
from soothe.core import ConfigDrivenPolicy  # Policy implementation
from soothe.core import FrameworkFilesystem # File backend
from soothe.core import resolve_daemon_workspace, validate_client_workspace
```

All exports are lazy-loaded in `__init__.py` to keep startup fast.

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
