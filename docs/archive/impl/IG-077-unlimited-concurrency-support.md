# IG-077: Unlimited Concurrency Support (0 = Unlimited)

**Status**: Draft
**Created**: 2026-03-28
**Related RFC**: RFC-202 (DAG-Based Execution and Unified Concurrency)

## Overview

Enhance the execution parallelism configuration to support `0 = unlimited` semantics across all concurrency limits. This allows operators to disable specific concurrency constraints without arbitrary upper bounds.

## Problem Statement

Current implementation:
- ConcurrencyPolicy uses positive integers for all limits
- asyncio.Semaphore requires positive integer (minimum 1)
- No way to express "unlimited" or "disabled limit"
- Config default values are conservative (1-5) which may be too restrictive for high-capacity deployments
- Operators cannot fully unlock parallelism for specific layers

## Proposed Solution

Implement "0 = unlimited" semantics:
1. **Protocol Layer**: Update `ConcurrencyPolicy` validation to allow 0 as special value
2. **Controller Layer**: Skip semaphore acquisition when limit is 0 (unlimited mode)
3. **Config Layer**: Update defaults and documentation
4. **Test Coverage**: Add tests for unlimited mode
5. **Documentation**: Update RFC-202 and user guide

## Implementation Plan

### Phase 1: Protocol Enhancement

**File**: `src/soothe/protocols/concurrency.py`

Changes:
1. Update docstrings to document 0 = unlimited semantics
2. Add validation hints in Field descriptions
3. No Pydantic validator needed (0 is valid int)

**Example**:
```python
max_parallel_goals: int = 1  # 0 = unlimited
max_parallel_steps: int = 1  # 0 = unlimited
max_parallel_subagents: int = 1  # 0 = unlimited (reserved)
max_parallel_tools: int = 10  # 0 = unlimited
global_max_llm_calls: int = 5  # 0 = unlimited (circuit breaker disabled)
```

### Phase 2: Controller Logic

**File**: `src/soothe/core/concurrency.py`

Changes:
1. Modify `ConcurrencyController.__init__` to handle 0-values
2. Skip semaphore creation for unlimited limits
3. Implement conditional acquisition in context managers

**Implementation**:
```python
def __init__(self, policy: ConcurrencyPolicy) -> None:
    self._policy = policy

    # Create semaphores only for positive limits
    # 0 = unlimited (no semaphore, no blocking)
    self._goal_sem = (
        asyncio.Semaphore(policy.max_parallel_goals)
        if policy.max_parallel_goals > 0
        else None
    )
    self._step_sem = (
        asyncio.Semaphore(policy.max_parallel_steps)
        if policy.max_parallel_steps > 0
        else None
    )
    self._llm_sem = (
        asyncio.Semaphore(policy.global_max_llm_calls)
        if policy.global_max_llm_calls > 0
        else None
    )
    self._tool_sem = (
        asyncio.Semaphore(policy.max_parallel_tools)
        if policy.max_parallel_tools > 0
        else None
    )

@asynccontextmanager
async def acquire_goal(self) -> AsyncGenerator[None]:
    """Acquire a goal execution slot.

    Unlimited mode (limit=0): No semaphore, passes through immediately.
    """
    if self._goal_sem is None:
        # Unlimited: no blocking
        yield
    else:
        # Limited: acquire semaphore
        async with self._goal_sem:
            yield

# Similar pattern for acquire_step(), acquire_llm_call(), acquire_tool()
```

### Phase 3: Property Accessors

**File**: `src/soothe/core/concurrency.py`

Add helper properties:
```python
@property
def has_goal_limit(self) -> bool:
    """Check if goal concurrency is limited."""
    return self._goal_sem is not None

@property
def has_step_limit(self) -> bool:
    """Check if step concurrency is limited."""
    return self._step_sem is not None

@property
def has_llm_limit(self) -> bool:
    """Check if LLM call circuit breaker is active."""
    return self._llm_sem is not None
```

### Phase 4: Configuration Updates

**File**: `src/soothe/config/config.yml`

Update defaults and documentation:
```yaml
execution:
  concurrency:
    max_parallel_goals: 1         # Max goals running simultaneously (0 = unlimited)
    max_parallel_steps: 3         # Max parallel plan steps (0 = unlimited)
    max_parallel_subagents: 3     # Max subagents simultaneously (0 = unlimited, reserved)
    max_parallel_tools: 9         # Max tools in parallel per step (0 = unlimited)
    global_max_llm_calls: 9       # Cross-level LLM call circuit breaker (0 = unlimited)
    step_parallelism: dependency  # sequential | dependency | max
```

### Phase 5: Test Coverage

**File**: `tests/unit/test_concurrency_controller.py`

Add test cases:
1. `test_unlimited_goal_passes_immediately()` - Verify 0-limit goals don't block
2. `test_unlimited_step_concurrent_execution()` - Verify 0-limit steps allow full parallelism
3. `test_unlimited_llm_calls()` - Verify 0-limit LLM circuit breaker disabled
4. `test_mixed_limits()` - Verify some limits active, others unlimited
5. `test_zero_policy_initialization()` - Verify controller handles all-0 policy

**Example Test**:
```python
async def test_unlimited_step_concurrent_execution() -> None:
    """Unlimited steps (limit=0) should allow any number of concurrent executions."""
    policy = ConcurrencyPolicy(max_parallel_steps=0)  # Unlimited
    controller = ConcurrencyController(policy)

    acquired = 0
    release = asyncio.Event()

    async def acquire_and_hold() -> None:
        nonlocal acquired
        async with controller.acquire_step():
            acquired += 1
            await release.wait()

    # Launch many concurrent tasks (more than previous limit)
    tasks = [asyncio.create_task(acquire_and_hold()) for _ in range(20)]
    await asyncio.sleep(0.05)

    # All should acquire immediately (no blocking)
    assert acquired == 20

    release.set()
    await asyncio.gather(*tasks)
```

### Phase 6: Documentation

**Files to Update**:
1. `docs/specs/RFC-202-dag-based-execution.md` - Add 0=unlimited semantics section
2. `docs/user_guide.md` - Update concurrency configuration section
3. `config/env.example` - Add comments for 0=unlimited
4. `src/soothe/config/config.yml` - Enhance inline comments

**RFC-202 Addition** (in Configuration section):
```markdown
### Unlimited Concurrency (Special Value: 0)

All concurrency limits support `0` as a special value meaning "unlimited":

- `max_parallel_goals: 0` → No limit on concurrent goals (autonomous mode)
- `max_parallel_steps: 0` → No limit on concurrent plan steps
- `max_parallel_tools: 0` → No limit on concurrent tool calls
- `global_max_llm_calls: 0` → Disable LLM call circuit breaker

**Implementation**: When a limit is set to 0, `ConcurrencyController` does not
create a semaphore for that layer. Acquisition becomes a no-op pass-through.

**Safety Consideration**:
- Unlimited `global_max_llm_calls` disables the cross-level circuit breaker,
  which may cause API rate-limit exhaustion in high-parallelism scenarios.
- Recommended: Keep at least one layer limited (e.g., global LLM calls) as a
  safety net.

**Example Configuration** (high-capacity deployment):
```yaml
execution:
  concurrency:
    max_parallel_goals: 0      # Unlimited goals
    max_parallel_steps: 0      # Unlimited steps
    max_parallel_tools: 0      # Unlimited tools
    global_max_llm_calls: 10   # Keep circuit breaker active (10 concurrent LLM calls)
```
```

## Verification Checklist

Before commit, run:
```bash
./scripts/verify_finally.sh
```

Manual verification:
1. ✓ ConcurrencyPolicy accepts 0 values (no Pydantic errors)
2. ✓ ConcurrencyController handles unlimited mode (no semaphore creation)
3. ✓ Unlimited acquisition passes through immediately (no blocking)
4. ✓ Tests pass for unlimited scenarios
5. ✓ Config defaults updated with 0 semantics documentation
6. ✓ RFC-202 updated with unlimited semantics section
7. ✓ User guide updated with configuration examples

## Backward Compatibility

- Existing configs with positive integers work unchanged
- No breaking changes to API or behavior
- Operators can gradually adopt 0 semantics as needed

## Estimated Effort

- Protocol Layer: 10 minutes (docstrings)
- Controller Logic: 30 minutes (semaphore handling)
- Property Accessors: 10 minutes (helper properties)
- Config Updates: 15 minutes (comments and defaults)
- Test Coverage: 40 minutes (5 new tests)
- Documentation: 30 minutes (RFC, user guide, env.example)
- **Total**: ~2.5 hours

## Implementation Order

1. Protocol Layer (Phase 1) - Foundation
2. Controller Logic (Phase 2-3) - Core implementation
3. Test Coverage (Phase 5) - Validate behavior
4. Configuration (Phase 4) - Update defaults
5. Documentation (Phase 6) - Update docs
6. Run verification script

## Success Criteria

1. All tests pass (existing + new unlimited tests)
2. Config with 0 values loads without errors
3. Unlimited mode allows full parallelism in practice
4. Documentation clearly explains 0 semantics
5. No lint errors or formatting issues