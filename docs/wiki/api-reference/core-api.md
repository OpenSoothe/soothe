# Core Framework (`soothe`)

The `soothe` package is the heart of the system — it provides the configuration model, the protocol abstractions that define every pluggable capability, the agent construction pipeline, and the execution runner. The daemon and SDK packages build on top of this foundation.

> **Source**: `packages/soothe/src/soothe/`

---

## Architectural Layers

Soothe separates concerns into three layers, each with a strict contract:

| Layer | Responsibility | Key Class |
|-------|---------------|-----------|
| **Layer 1** | Pure agent execution — tools, subagents, middleware, LangGraph runtime | `CoreAgent` |
| **Layer 2** | Goal-driven orchestration — planning, strange-loop iteration, thread management | `SootheRunner` |
| **Layer 3** | Daemon infrastructure — IPC, multi-transport, background scheduling | `SootheDaemon` |

Layer 1 knows nothing about goals or the daemon. Layer 2 wraps Layer 1 with protocol orchestration. Layer 3 (documented in [daemon-api.md](daemon-api.md)) hosts Layer 2 as a long-running server.

This separation is intentional: `CoreAgent` can be used standalone for embedding in any async Python process, while `SootheRunner` adds the agentic loop and protocol pre/post-processing.

---

## Configuration System

`SootheConfig` (`packages/soothe/src/soothe/config/settings.py`) is a Pydantic `BaseSettings` model that holds the entire agent configuration tree. It is the single entry point for all configuration — providers, models, agent behavior, protocols, persistence, observability, security, subagents, and MCP servers.

### Key Design Decisions

- **Environment variable interpolation**: Every string value supports `${ENV_VAR}` syntax, recursively expanded across the entire config tree (not just leaf values). Unresolved placeholders are left intact rather than raising.
- **Dual config source**: Values can come from a YAML file (`from_yaml_file`) or environment variables with the `SOOTHE_` prefix. Nested fields use `__` as separator — e.g., `SOOTHE_PROVIDERS__OPENAI__API_KEY`.
- **`.env` loading happens before imports**: The daemon bootstrap calls `bootstrap_dotenv()` before any langchain imports so provider API keys are visible at import time.
- **Lazy LLM factory**: The `_llm_factory` is lazily initialized to avoid paying provider import costs until a model is actually requested.

### Model Routing

`ModelRouter` maps *roles* (not tasks) to `provider:model` strings: `default`, `planner`, `subagent`, `embedding`, `classify`. This indirection lets you swap the planner model without touching agent code. The `resolve_model(role)` and `create_chat_model(role)` methods bridge config to LangChain `BaseChatModel` instances.

The `propagate_env()` method exports resolved API keys into `os.environ` so downstream libraries (openai, anthropic SDKs) pick them up without explicit passing — important when MCP servers or subagents initialize their own clients.

### Minimal Config Example

```yaml
providers:
  openai:
    type: openai
    api_key: ${OPENAI_API_KEY}
models:
  default: openai:gpt-4o
  planner: openai:gpt-4o
  subagent: openai:gpt-4o-mini
```

> Full field reference: `packages/soothe/src/soothe/config/models.py`

---

## Protocol Definitions

Protocols are runtime-agnostic `typing.Protocol` interfaces that define *what* a capability does, decoupled from *how* it's implemented. The core package defines them; backends implement them; the runner resolves which implementation to use based on config.

> **Source**: `packages/soothe/src/soothe/protocols/`

| Protocol | Purpose | RFC | Backends |
|----------|---------|-----|----------|
| `MemoryProtocol` | Remember/recall agent memories with scoped search | RFC-301 | `MemUMemory` |
| `DurabilityProtocol` | Thread lifecycle: create, suspend, resume, archive, list | RFC-304 | `SQLiteDurability`, `PostgreSQLDurability` |
| `PlannerProtocol` | Goal decomposition into steps + completion assessment | RFC-305 | `LLMPlanner` |
| `PolicyProtocol` | Permission enforcement + child-agent permission narrowing | RFC-306 | `ConfigDrivenPolicy` |
| `VectorStoreProtocol` | Vector add/search/delete with metadata filtering | RFC-303 | `PGVectorStore`, `SQLiteVecStore`, `WeaviateStore` |
| `AsyncPersistStore` | Async key-value persistence (bytes values) | RFC-302 | `SQLitePersistStore`, `PostgreSQLPersistStore` |
| `IdentityProtocol` | Token issuance, auth, external identity mapping | RFC-307 | (re-exported from SDK) |

### Why Protocols, Not ABCs?

The protocols use `typing.Protocol` (structural subtyping) rather than `abc.ABC` (nominal subtyping). This means a third-party class can satisfy a protocol *without* importing it — critical for plugin authors who want zero hard dependencies on the core package. The SDK re-exports the same protocol definitions so plugin authors can type-check against them without pulling in daemon code.

### Memory Scoping

`MemoryProtocol.remember/recall` take a `scope` parameter: `thread`, `workspace`, `user`, or `global`. The scope determines visibility — a thread-scoped memory is invisible to other threads, even in the same workspace. This is the mechanism behind per-conversation context isolation.

---

## Agent Construction

> **Source**: `packages/soothe/src/soothe/foundation/core/agent/`

### CoreAgent (Layer 1)

`CoreAgent` is a thin typed wrapper around LangGraph's `CompiledStateGraph`. It exposes protocol instances (memory, planner, policy) as typed properties and provides the `astream()` execution interface. It deliberately contains **no goal infrastructure** — that's Layer 2's job.

A key design detail: `CoreAgent` can hold a *twin* execute graph (`execute_graph`) compiled without a checkpointer, used for ephemeral execute-phase streaming (IG-477). This avoids checkpoint pollution from the StrangeLoop's ACT phase.

### AgentBuilder & create_soothe_agent()

`AgentBuilder` encapsulates the complex construction pipeline: protocol resolution, middleware stack assembly, backend initialization, plugin loading, and MCP registry integration. The convenience function `create_soothe_agent()` is the standard entry point — it creates an `AgentBuilder`, resolves all protocols from config, and builds the agent.

The middleware stack (assembled in `build_soothe_middleware_stack`) is ordered:

1. **PolicyMiddleware** — safety enforcement (runs first, can block)
2. **SystemPromptMiddleware** — dynamic prompt injection based on classification
3. **WorkspaceContextMiddleware** — binds thread to a workspace path
4. **SubagentContextMiddleware** — injects context briefing for delegation

### Minimal Agent Creation

```python
from soothe.foundation.core.agent import create_soothe_agent
from soothe.config import SootheConfig

agent = create_soothe_agent(SootheConfig.from_yaml_file("config.yml"))
```

For custom protocol injection (e.g., a test-memory backend), use `AgentBuilder` directly with `.with_memory()`, `.with_policy()`, etc.

---

## Agent Execution (Layer 2)

> **Source**: `packages/soothe/src/soothe/runner/`

### SootheRunner

`SootheRunner` wraps `create_soothe_agent()` with protocol pre/post-processing and the agentic loop. It is decomposed into four mixins:

| Mixin | Phase |
|-------|-------|
| `PhasesMixin` | Pre-stream: thread binding, policy setup, memory recall, plan bootstrap |
| `StrangeLoopMixin` | The Reason→Act iterative loop (RFC-201, RFC-220) |
| `AutopilotWorkerMixin` | Single-goal worker entry for daemon-dispatched goals (RFC-222) |
| `CheckpointMixin` | Progressive checkpointing, artifacts, reports (RFC-0010) |

The runner's `astream()` method yields `StreamChunk` objects — a normalized `(namespace, mode, data)` tuple that extends the raw LangGraph stream with `soothe.*` custom events for protocol observability. Namespaces include `assistant` (model output), `tool` (tool execution), and `soothe` (protocol-level events like memory recall or policy checks).

### Gotcha: Thread ID vs Loop ID

There are two distinct identifiers that are easy to confuse:
- **`thread_id`** — the LangGraph/durability checkpoint key (`configurable.thread_id`). This is what persists conversation state.
- **`loop_id`** — the StrangeLoop subscription scope for event streaming. A loop *contains* one or more threads.

The daemon's command handlers receive `loop_id` on the wire but internally bind it to a `checkpoint_thread_id` before executing. See `packages/soothe-daemon/src/soothe_daemon/server/commands.py` for the binding logic.

### Gotcha: Autopilot is Daemon-Owned

The legacy in-process autonomous multi-goal loop has been removed (RFC-222 Phase D). Autopilot goals are dispatched *by the daemon* and arrive through `LoopRunRequest.autopilot_job`, routing to the single-goal worker path. You cannot run autopilot from a bare `SootheRunner` — it requires the daemon's goal dispatch infrastructure.

---

## Backend Implementations

Backends are concrete protocol implementations. They live in `packages/soothe/src/soothe/backends/` and are resolved by `packages/soothe/src/soothe/runner/resolver/`.

### Resolution Pattern

The resolver functions (`resolve_memory`, `resolve_durability`, `resolve_planner`, `resolve_policy`, `resolve_checkpointer`) read config flags and instantiate the appropriate backend. Each is a simple factory — if the protocol is disabled in config, it returns `None`. This means a missing backend dependency (e.g., `psycopg` not installed) only matters if you actually enable that backend.

### Backend Selection Guide

| Need | Backend | Config Flag |
|------|---------|-------------|
| Local dev / single user | `SQLiteDurability` + `SQLitePersistStore` | `backend: sqlite` |
| Production / multi-agent | `PostgreSQLDurability` + `PostgreSQLPersistStore` | `backend: postgresql` |
| Semantic memory | `MemUMemory` | `memory.enabled: true` |
| Vector search (local) | `SQLiteVecStore` | `vector_store.default: sqlite_vec` |
| Vector search (production) | `PGVectorStore` | `vector_store.default: pgvector` |
| Policy enforcement | `ConfigDrivenPolicy` | `policy.enabled: true` |

### Policy Profiles

`ConfigDrivenPolicy` supports named profiles (`readonly`, `standard`, `privileged`) with permission grants and `deny_by_default` toggles. The `narrow_for_child()` method is critical for subagent security — it derives a restricted permission set for a delegated subagent, ensuring a child agent never has *more* permissions than its parent.

---

## See Also

- [Daemon API](daemon-api.md) — Layer 3 server infrastructure
- [SDK API](sdk-api.md) — Client and plugin development
- [Protocols Layer](../protocols/README.md) — Protocol specifications
- [Configuration Guide](../configuration-guide/README.md) — Full config reference
- [RFC-000 System Design](../../specs/RFC-000-system-conceptual-design.md) — Architecture RFCs
