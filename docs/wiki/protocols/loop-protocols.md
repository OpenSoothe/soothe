# Loop-Level Protocols

**RFCs**: RFC-203 (LoopWorkingMemory), RFC-220 (StrangeLoop), RFC-604 (LoopPlanner)  
**Locations**:
- `packages/soothe/src/soothe/protocols/loop_working_memory.py`
- `packages/soothe/src/soothe/protocols/loop_planner.py`
- `packages/soothe/src/soothe/protocols/operation_security.py`

**Status**: Implemented  

## Overview

Loop-level protocols define interfaces specific to StrangeLoop execution:

1. **LoopWorkingMemoryProtocol**: Bounded scratchpad for Plan prompts
2. **LoopPlannerProtocol**: Unified Plan phase (covered in [Planner Protocol](planner.md))
3. **OperationSecurityProtocol**: Operation-level security context

These protocols support StrangeLoop's Plan → Execute cycle, providing bounded memory, planning decisions, and operation-level security.

## LoopWorkingMemoryProtocol

### Purpose

- **Bounded scratchpad**: Keep working memory within prompt limits
- **Step result recording**: Track Act step outcomes
- **Reason prompt injection**: Render memory for planning decisions
- **Optional workspace spill**: Overflow to workspace when bounded

### Protocol Interface

```python
class LoopWorkingMemoryProtocol(Protocol):
    """Bounded working memory for StrangeLoop Plan prompts.
    
    Optional workspace spill when bounded memory exceeds limits.
    """

    def clear(self) -> None:
        """Reset for a new goal."""
        ...

    def record_step_result(
        self,
        *,
        step_id: str,
        description: str,
        output: str | None,
        error: str | None,
        success: bool,
        workspace: str | None,
        thread_id: str,
    ) -> None:
        """Record one Act step outcome.
        
        Args:
            step_id: The step that was executed.
            description: Step description from plan.
            output: Tool/subagent output (truncated preview).
            error: Error message if failed.
            success: Whether step succeeded.
            workspace: Workspace path used.
            thread_id: Thread ID for context.
        """
        ...

    def render_for_reason(self, *, max_chars: int | None = None) -> str:
        """Return text for Reason prompt injection.
        
        Args:
            max_chars: Maximum characters to render (None = no limit).
            
        Returns:
            Formatted working memory text.
        """
        ...
```

### Design Principles

#### Bounded Memory

Working memory is bounded to prevent prompt overflow:

```
Goal → Plan → Execute → Record → WorkingMemory

Plan Phase:
  - WorkingMemory.render_for_reason(max_chars=2000)
  - Bounded view injected into planner prompt
  - Planner sees recent step results, not full history
  
Execute Phase:
  - Record new step results
  - Working memory grows (bounded)
  - Optional: spill to workspace file
```

#### Step Result Recording

Each Act step records outcome:

```python
working_memory.record_step_result(
    step_id="S_1",
    description="Research database optimization techniques",
    output="Found PostgreSQL tuning guide...",
    error=None,
    success=True,
    workspace="/project/workspace",
    thread_id="thread_abc123"
)
```

### Implementation

#### Default Implementation

**Location**: `packages/soothe/src/soothe/core/loop/engine/working_memory.py`

**Features**:
- In-memory bounded list
- Truncated output previews
- Error tracking
- Workspace spill support (optional)

**Example**:
```python
class DefaultWorkingMemory(LoopWorkingMemoryProtocol):
    """Default bounded working memory implementation."""
    
    def __init__(self, max_entries: int = 20) -> None:
        self._entries: list[StepResultEntry] = []
        self._max_entries = max_entries
    
    def clear(self) -> None:
        """Reset for new goal."""
        self._entries = []
    
    def record_step_result(...) -> None:
        """Record step outcome."""
        entry = StepResultEntry(
            step_id=step_id,
            description=description,
            output_preview=self._truncate(output, max_len=200),
            error=error,
            success=success,
            workspace=workspace,
            thread_id=thread_id,
            timestamp=datetime.utcnow()
        )
        
        self._entries.append(entry)
        
        # Bounded: remove oldest if exceeds limit
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)
    
    def render_for_reason(self, *, max_chars: int | None = None) -> str:
        """Render bounded view for planner."""
        text = "\n".join([
            f"[{entry.step_id}] {entry.description}"
            f" → {entry.output_preview or entry.error}"
            for entry in self._entries
        ])
        
        if max_chars:
            text = text[:max_chars]
        
        return text
```

### Usage Patterns

#### StrangeLoop Integration

```python
from soothe.protocols import LoopWorkingMemoryProtocol

# Initialize working memory for loop
working_memory: LoopWorkingMemoryProtocol = DefaultWorkingMemory()

# Clear for new goal
working_memory.clear()

# During Execute phase:
for step in plan.steps:
    result = await execute_step(step)
    
    # Record outcome
    working_memory.record_step_result(
        step_id=step.id,
        description=step.description,
        output=result.preview,
        error=result.error,
        success=result.success,
        workspace=current_workspace,
        thread_id=current_thread
    )

# During Plan phase:
memory_text = working_memory.render_for_reason(max_chars=2000)

# Inject into planner prompt
planner_prompt = f"""
Recent progress:
{memory_text}

Goal: {goal}
Capabilities: {capabilities}

Generate next execution step...
"""
```

#### Workspace Spill

When bounded memory exceeds limits, overflow to workspace:

```python
# Optional: spill to file
if len(working_memory._entries) > MAX_ENTRIES:
    spill_file = workspace / ".soothe" / "working_memory_spill.json"
    spill_file.write_text(working_memory.serialize_entries())
    
    # Keep recent entries in bounded memory
    working_memory._entries = working_memory._entries[-MAX_ENTRIES:]
```

## OperationSecurityProtocol

### Purpose

- **Operation-level context**: Security context for individual operations
- **Request/decision tracking**: Track security requests and decisions
- **Context propagation**: Propagate security context to tools/subagents

### Protocol Interface

```python
@runtime_checkable
class OperationSecurityProtocol(Protocol):
    """Protocol for operation-level security context.
    
    Tracks security context for individual operations (tool calls,
    subagent spawns, MCP connections).
    """

    async def check_operation(
        self,
        request: OperationSecurityRequest,
        context: OperationSecurityContext,
    ) -> OperationSecurityDecision:
        """Check if operation is permitted.
        
        Args:
            request: The operation being requested.
            context: Current operation security context.
            
        Returns:
            OperationSecurityDecision (allow/deny/need_approval).
        """
        ...
```

### Data Models

#### OperationKind

```python
class OperationKind(str, Enum):
    """Types of operations requiring security checks.
    
    Values:
        tool_call: Direct tool invocation.
        subagent_spawn: Subagent creation/delegation.
        mcp_connect: MCP server connection.
        remote_invoke: Remote agent invocation.
    """

    tool_call = "tool_call"
    subagent_spawn = "subagent_spawn"
    mcp_connect = "mcp_connect"
    remote_invoke = "remote_invoke"
```

#### OperationSecurityRequest

```python
class OperationSecurityRequest(BaseModel):
    """Request to perform an operation requiring security check.
    
    Args:
        kind: Type of operation.
        target: Operation target (tool name, subagent name, MCP server).
        parameters: Operation parameters.
        delegation_depth: Current delegation depth.
    """

    kind: OperationKind
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    delegation_depth: int = 0
```

#### OperationSecurityContext

```python
class OperationSecurityContext(BaseModel):
    """Context for operation security decisions.
    
    Args:
        thread_id: Current thread ID.
        policy_profile: Active policy profile.
        workspace: Current workspace path.
        parent_permissions: Permission set from parent operation.
    """

    thread_id: str | None = None
    policy_profile: str = "standard"
    workspace: str | None = None
    parent_permissions: PermissionSet | None = None
```

#### OperationSecurityDecision

```python
class OperationSecurityDecision(BaseModel):
    """Decision from operation security check.
    
    Args:
        allowed: Whether operation is permitted.
        reason: Explanation for decision.
        audit_required: Whether operation requires audit logging.
        narrowed_permissions: Permission set for child operations.
    """

    allowed: bool
    reason: str
    audit_required: bool = False
    narrowed_permissions: PermissionSet | None = None
```

### Usage Patterns

#### Tool Call Security

```python
from soothe.protocols import (
    OperationSecurityProtocol,
    OperationSecurityRequest,
    OperationSecurityContext,
    OperationKind
)

security: OperationSecurityProtocol = resolve_security(config)

# Check tool call
request = OperationSecurityRequest(
    kind=OperationKind.tool_call,
    target="shell_execute",
    parameters={"command": "rm -rf /tmp/cache"},
    delegation_depth=0
)

context = OperationSecurityContext(
    thread_id="thread_abc123",
    policy_profile="standard",
    workspace="/project/workspace"
)

decision = await security.check_operation(request, context)

if decision.allowed:
    # Execute tool
    result = await execute_tool("shell_execute", command="rm -rf /tmp/cache")
    
    # Audit if required
    if decision.audit_required:
        audit_logger.log_operation(request, context, decision)
else:
    # Deny operation
    raise PermissionError(decision.reason)
```

#### Subagent Spawn Security

```python
# Check subagent spawn
request = OperationSecurityRequest(
    kind=OperationKind.subagent_spawn,
    target="explore",
    parameters={"goal": "Search for database files"},
    delegation_depth=1  # Child delegation
)

decision = await security.check_operation(request, context)

if decision.allowed:
    # Create subagent with narrowed permissions
    subagent = create_subagent(
        name="explore",
        permissions=decision.narrowed_permissions  # Narrowed from parent
    )
```

#### MCP Connection Security

```python
# Check MCP connection
request = OperationSecurityRequest(
    kind=OperationKind.mcp_connect,
    target="filesystem-server",
    parameters={},
    delegation_depth=0
)

decision = await security.check_operation(request, context)

if decision.allowed:
    # Connect to MCP server
    mcp_client = await connect_mcp_server("filesystem-server")
```

### Integration with PolicyProtocol

OperationSecurityProtocol uses PolicyProtocol for decisions:

```python
class DefaultOperationSecurity(OperationSecurityProtocol):
    """Default implementation using PolicyProtocol."""
    
    def __init__(self, policy: PolicyProtocol) -> None:
        self._policy = policy
    
    async def check_operation(
        self,
        request: OperationSecurityRequest,
        context: OperationSecurityContext,
    ) -> OperationSecurityDecision:
        # Convert to PolicyProtocol request
        action_request = ActionRequest(
            action=self._convert_operation_to_permission(request),
            delegation_depth=request.delegation_depth
        )
        
        policy_context = PolicyContext(
            profile=context.policy_profile,
            thread_id=context.thread_id,
            delegation_depth=request.delegation_depth
        )
        
        # Use PolicyProtocol for decision
        policy_decision = self._policy.check(action_request, policy_context)
        
        # Convert to operation decision
        return OperationSecurityDecision(
            allowed=policy_decision.allowed,
            reason=policy_decision.reason,
            audit_required=self._should_audit(request),
            narrowed_permissions=self._narrow_permissions(request, context)
        )
```

## Configuration

### WorkingMemory Settings

```yaml
# config/config.template.yml
agent:
  loop:
    working_memory:
      max_entries: 20
      max_chars_per_entry: 200
      spill_to_workspace: false
```

### OperationSecurity Settings

```yaml
agent:
  security:
    audit_operations:
      - tool_call
      - subagent_spawn
    audit_log_path: ~/.soothe/logs/operations.log
```

## Testing

### Unit Tests

Tests verify:
- Working memory bounded limits
- Step result recording accuracy
- Reason prompt rendering
- Operation security decisions
- Permission narrowing

## Design Rationale

### Why Bounded Working Memory?

Prompt efficiency:
- Planner only needs recent results
- Full history is in Context (unbounded)
- Working memory is bounded view
- Prevents prompt token exhaustion

### Why Operation-Level Security?

Fine-grained control:
- Each operation needs security check
- Delegation depth tracking
- Permission narrowing for children
- Audit trail for sensitive operations

### Why Separate from PolicyProtocol?

Different abstraction levels:
- **PolicyProtocol**: Profile-based permission management
- **OperationSecurityProtocol**: Operation-level context and decisions
- Operation security delegates to policy for core decisions

## Specification Reference

- **RFC-203**: StrangeLoop State Memory
- **RFC-604**: Reason Phase Robustness
- **RFC-220**: LangGraph Agent Loop Orchestrator
- **RFC-901**: Operation Security Protocol

## Related Documentation

- [Planner Protocol](planner.md)
- [Policy Protocol](policy.md)
- [StrangeLoop Architecture](../sloop.md)
- [Security Enforcement](../security.md)