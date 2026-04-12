# RFC-301: Protocol Registry

**Status**: Implemented
**Authors**: Xiaming Chen
**Created**: 2026-03-31
**Last Updated**: 2026-03-31
**Depends on**: RFC-001 (Core Modules Architecture), RFC-300 (Context & Memory Protocols)
**Supersedes**: ---
**Kind**: Implementation Interface Design

---

## 1. Abstract

This RFC defines the interface contracts for Soothe's protocol layer excluding Context and Memory (covered in RFC-300). It specifies PlannerProtocol, PolicyProtocol, DurabilityProtocol, RemoteAgentProtocol, and VectorStoreProtocol with their data structures, method signatures, and implementation patterns.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* Interface contracts for 5 core protocols
* Data structures used across protocol implementations
* Naming conventions for protocol implementations
* Backend discovery and configuration patterns

### 2.2 Non-Goals

This RFC does **not** define:

* ContextProtocol and MemoryProtocol (see RFC-300)
* Concrete backend implementations (see respective backend modules)
* Protocol composition and wiring (see RFC-001 Core Modules)

---

## 3. Background & Motivation

RFC-0002 introduced the protocol abstraction layer but scattered protocol definitions across multiple RFCs. This registry consolidates interface contracts in one place, enabling:

1. **Clear contracts** — Implementers know exactly what to implement
2. **Type safety** — `@runtime_checkable` Protocol classes for static analysis
3. **Backend discovery** — Naming convention enables automatic backend resolution
4. **Testability** — Easy to mock protocols in unit tests

---

## 4. Naming Conventions

### 4.1 Protocol Implementation Names

Pattern: `{Method}{Protocol}` where `{Method}` describes the implementation approach.

| Protocol | Implementation Pattern | Examples |
|----------|----------------------|----------|
| PlannerProtocol | `LLMPlanner` | `LLMPlanner` (after IG-150 consolidation) |
| PolicyProtocol | `{Source}Policy` | `ConfigDrivenPolicy`, `DatabasePolicy` |
| DurabilityProtocol | `{Store}Durability` | `JsonDurability`, `PostgreSQLDurability` |
| RemoteAgentProtocol | `{Transport}RemoteAgent` | `LangGraphRemoteAgent`, `A2ARemoteAgent` |
| VectorStoreProtocol | `{Provider}VectorStore` | `PGVectorStore`, `WeaviateStore`, `InMemoryVectorStore` |

### 4.2 Configuration Keys

Protocol configuration follows nested structure:

```yaml
protocols:
  planner:
    backend: claude        # simple | claude | auto
  policy:
    backend: config_driven  # config_driven | database
    profile: standard       # readonly | standard | privileged
  durability:
    backend: postgresql     # json | rocksdb | postgresql
  remote:
    enabled: true
  vector_store:
    router:
      default: pgvector_default
```

---

## 5. Data Structures

### 5.1 PlannerProtocol Data Structures

#### PlanStep

```python
class PlanStep(BaseModel):
    id: str                          # Unique step identifier
    description: str                 # What this step should accomplish
    execution_hint: Literal["tool", "subagent", "remote", "auto"] = "auto"
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    result: str | None = None        # Output from execution
    depends_on: list[str] = []       # IDs of prerequisite steps
    current_activity: str | None = None  # Latest activity (TUI rendering)
```

#### Plan

```python
class Plan(BaseModel):
    id: str = ""                     # Plan identifier (P_1, P_2, etc.)
    goal: str                        # Original goal text
    steps: list[PlanStep]            # Ordered step list
    current_index: int = 0           # Next step to execute
    status: Literal["active", "completed", "failed", "revised"] = "active"
    concurrency: ConcurrencyPolicy   # Parallel execution config
    general_activity: str | None = None  # Non-step activity (TUI)
```

#### Reflection

```python
class Reflection(BaseModel):
    assessment: str                  # Progress description
    should_revise: bool              # Needs revision?
    feedback: str                    # Revision guidance
    blocked_steps: list[str] = []    # Dependency-blocked steps
    failed_details: dict[str, str] = {}  # Step ID → error
    goal_directives: list[GoalDirective] = []  # Goal management actions
```

### 5.2 PolicyProtocol Data Structures

#### Permission

```python
@dataclass(frozen=True)
class Permission:
    category: str                    # fs | shell | net | mcp | subagent
    action: str                      # read | write | execute | connect | spawn
    scope: str = "*"                 # "*" | glob | "!glob" (negation)
```

| Category | Actions | Scope Examples |
|----------|---------|----------------|
| `fs` | `read`, `write` | `*`, `/tmp/**`, `/home/user/*.txt` |
| `shell` | `execute` | `*`, `ls`, `!rm` (negation) |
| `net` | `outbound` | `*.example.com`, `*` |
| `mcp` | `connect` | `my-server`, `*` |
| `subagent` | `spawn` | `planner`, `research`, `*` |

#### PolicyDecision

```python
class PolicyDecision(BaseModel):
    verdict: Literal["allow", "deny", "need_approval"]
    reason: str                      # Human-readable explanation
    matched_permission: Permission | None = None
```

### 5.3 DurabilityProtocol Data Structures

#### ThreadMetadata

```python
class ThreadMetadata(BaseModel):
    tags: list[str] = []
    plan_summary: str | None = None
    policy_profile: str = "standard"
    labels: list[str] = []           # User-defined labels
    priority: Literal["low", "normal", "high"] = "normal"
    category: str | None = None
```

#### ThreadInfo

```python
class ThreadInfo(BaseModel):
    thread_id: str
    status: Literal["active", "suspended", "archived"]
    created_at: datetime
    updated_at: datetime
    metadata: ThreadMetadata
```

### 5.4 VectorStoreProtocol Data Structures

#### VectorRecord

```python
class VectorRecord(BaseModel):
    id: str                          # Unique record identifier
    score: float | None = None       # Similarity score (search results)
    payload: dict[str, Any] = {}     # Stored metadata
```

---

## 6. Interface Contracts

### 6.1 PlannerProtocol

```python
@runtime_checkable
class PlannerProtocol(Protocol):
    async def create_plan(self, goal: str, context: PlanContext) -> Plan:
        """Decompose goal into structured plan."""
        ...

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan:
        """Revise plan based on feedback."""
        ...

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
    ) -> Reflection:
        """Evaluate progress and recommend changes."""
        ...

    async def reason(
        self,
        goal: str,
        context: PlanContext,
        previous_reason: Any | None = None,
    ) -> Any:
        """Produce PlanResult for Layer 2 execution loop."""
        ...
```

### 6.2 PolicyProtocol

```python
@runtime_checkable
class PolicyProtocol(Protocol):
    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if action is permitted."""
        ...

    def narrow_for_child(
        self,
        parent_permissions: PermissionSet,
        child_name: str,
    ) -> PermissionSet:
        """Compute narrowed permissions for child subagent."""
        ...
```

### 6.3 DurabilityProtocol

```python
@runtime_checkable
class DurabilityProtocol(Protocol):
    async def create_thread(
        self,
        metadata: ThreadMetadata,
        thread_id: str | None = None,
    ) -> ThreadInfo:
        """Create new thread."""
        ...

    async def resume_thread(self, thread_id: str) -> ThreadInfo:
        """Resume suspended thread."""
        ...

    async def suspend_thread(self, thread_id: str) -> None:
        """Suspend active thread."""
        ...

    async def archive_thread(self, thread_id: str) -> None:
        """Archive thread, trigger memory consolidation."""
        ...

    async def update_thread_metadata(
        self,
        thread_id: str,
        metadata: dict[str, Any] | ThreadMetadata,
    ) -> None:
        """Update thread metadata (partial merge)."""
        ...

    async def list_threads(
        self,
        thread_filter: ThreadFilter | None = None,
    ) -> list[ThreadInfo]:
        """List threads matching filter."""
        ...
```

### 6.4 RemoteAgentProtocol

```python
@runtime_checkable
class RemoteAgentProtocol(Protocol):
    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Invoke remote agent, return result."""
        ...

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream results from remote agent."""
        ...

    async def health_check(self) -> bool:
        """Check if remote agent is reachable."""
        ...
```

### 6.5 VectorStoreProtocol

```python
@runtime_checkable
class VectorStoreProtocol(Protocol):
    async def create_collection(
        self,
        vector_size: int,
        distance: str = "cosine",
    ) -> None:
        """Create or ensure collection exists."""
        ...

    async def insert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]] | None = None,
        ids: list[str] | None = None,
    ) -> None:
        """Insert vectors with optional payloads."""
        ...

    async def search(
        self,
        query: str,
        vector: list[float],
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorRecord]:
        """Search for nearest neighbours."""
        ...

    async def delete(self, record_id: str) -> None:
        """Delete record by ID."""
        ...

    async def update(
        self,
        record_id: str,
        vector: list[float] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Update record's vector and/or payload."""
        ...

    async def get(self, record_id: str) -> VectorRecord | None:
        """Retrieve single record by ID."""
        ...

    async def list_records(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[VectorRecord]:
        """List records matching filters."""
        ...

    async def delete_collection(self) -> None:
        """Delete entire collection."""
        ...

    async def reset(self) -> None:
        """Clear all records without deleting collection."""
        ...

    async def close(self) -> None:
        """Close connections, release resources."""
        ...
```

---

## 7. Implementation Patterns

### 7.1 Backend Resolution

Protocol backends are resolved from configuration:

```python
def resolve_planner(config: SootheConfig) -> PlannerProtocol:
    """Resolver returns LLMPlanner directly (IG-150 consolidation)."""
    return LLMPlanner(
        model=config.create_chat_model(config.protocols.planner.model),
        config=config
    )
```

### 7.2 Protocol Composition

Protocols are composed in `SootheRunner`:

```python
class SootheRunner:
    def __init__(self, config: SootheConfig):
        self.planner = resolve_planner(config)
        self.policy = resolve_policy(config)
        self.durability = resolve_durability(config)
        self.context = resolve_context(config)
        self.memory = resolve_memory(config)
        self.vector_store = resolve_vector_store(config)
```

### 7.3 Error Handling

| Error Category | Handling Approach |
|----------------|-------------------|
| `KeyError` (thread not found) | Raise to caller, convert to user message |
| `ValueError` (invalid backend) | Fail fast at startup |
| `ConnectionError` (remote/vector) | Retry with backoff, graceful degradation |
| `PermissionDenied` | Log audit, return deny decision |

---

## 8. Examples

### 8.1 Permission Check Flow

```python
# Tool invocation request
action = ActionRequest(
    action_type="tool_call",
    tool_name="execute",
    tool_args={"command": "rm -rf /tmp/*"},
)

context = PolicyContext(
    active_permissions=PermissionSet({
        Permission("shell", "execute", "!rm"),  # Deny rm
        Permission("shell", "execute", "ls"),   # Allow ls
    }),
)

decision = policy.check(action, context)
# → PolicyDecision(verdict="deny", reason="rm is explicitly denied")
```

### 8.2 Planner Plan Creation

```python
context = PlanContext(
    recent_messages=["User wants to analyze sales data"],
    available_capabilities=["execute", "websearch", "research_subagent"],
)

plan = await planner.create_plan(
    goal="Analyze Q4 sales data and generate report",
    context=context,
)
# → Plan with steps: [fetch_data, analyze, generate_report]
```

---

## 9. Relationship to Other RFCs

* **RFC-001 (Core Modules Architecture)**: Protocol composition in `SootheRunner`
* **RFC-300 (Context & Memory Protocols)**: Sister RFC for context/memory interfaces
* **RFC-102 (Security & Policy)**: PolicyProtocol security details
* **RFC-200 (Autonomous Goal Management)**: PlannerProtocol goal lifecycle
* **RFC-202 (DAG Execution)**: PlannerProtocol DAG support

---

## 10. Open Questions

1. **JudgeProtocol** — Should judge be added to registry or kept separate in cognition layer?
2. **PersistStore** — Currently in RFC-300, should it move here as cross-protocol dependency?
3. **Protocol versioning** — How to handle breaking changes to protocol interfaces?

---

## 11. Conclusion

This registry provides clear interface contracts for Soothe's protocol layer, enabling backend swappability, testability, and type safety. Together with RFC-300, it documents all 8 core protocols that form the abstraction backbone of the system.

> **Protocols define what; backends define how.**