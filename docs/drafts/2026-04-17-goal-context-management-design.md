# Goal Context Management Design Draft

**Date**: 2026-04-17  
**Status**: Draft  
**Scope**: AgentLoop context management for Plan-Execute loops  
**Related**: RFC-200 (Agentic Goal Execution), RFC-608 (Multi-Thread Lifecycle)

## Abstract

Design a unified goal-level context management system for AgentLoop that mirrors CoreAgent's context separation pattern. Goal-level summaries (loop checkpoint) are injected separately from conversation history (thread state), enabling seamless same-thread continuation and thread-switch knowledge transfer while maintaining architectural isolation.

## Problem Statement

### Current Issue

AgentLoop's `inject_previous_goal_context()` method exists but is never called. Previous goal final_reports are not injected into Plan or Execute phases, causing:

1. **Same-thread continuation failure**: "translate to chinese" after "analyze performance" asks "please provide text" instead of translating previous report
2. **Thread switch knowledge loss**: When RFC-608 thread switching occurs, CoreAgent on new thread has no conversation history and no goal-level context

### Architecture Principle

CoreAgent pattern:
- Conversation history: LangGraph thread state (raw messages)
- Execution context: config.configurable briefings

AgentLoop should mirror this:
- Goal-level history: loop checkpoint goal_history (summaries, not messages)
- Iteration context: LoopState.plan_conversation_excerpts

**Key constraint**: Keep loop history (goals) separate from thread history (messages).

## Solution: Unified Goal Context Manager

Create `GoalContextManager` module that provides goal-level context for both Plan and Execute phases:

```python
class GoalContextManager:
    """Unified goal-level context provider for AgentLoop.
    
    Mirrors CoreAgent's separation: conversation history (thread state) vs
    goal-level summaries (loop checkpoint). Provides previous goal context
    for LLM reasoning while keeping CoreAgent conversation isolated.
    
    Injection rules:
    - Plan phase: ALWAYS inject previous goal summaries (LLM needs goal-level
      context for strategy decisions, regardless of thread continuity)
    - Execute phase: ONLY inject on thread switch (when CoreAgent conversation
      history is lost, goal briefing provides essential knowledge transfer)
    
    Same-thread constraint: Plan phase only injects goals from current thread.
    Cross-thread scope: Execute briefing includes goals from all threads.
    """
    
    def get_plan_context(self, limit: int = 10) -> list[str]:
        """Get previous goal summaries for Plan phase (XML blocks).
        
        Always injects - Plan phase needs goal-level strategy context
        even when CoreAgent has conversation continuity.
        
        Same-thread constraint: Only goals from checkpoint.current_thread_id.
        
        Returns XML-formatted goal summaries:
        <previous_goal>
        Goal: <query>
        Status: completed
        Thread: <thread_id>
        Output: <final_report>
        </previous_goal>
        """
        
    def get_execute_briefing(self, limit: int = 10) -> str | None:
        """Get goal briefing for Execute phase (only on thread switch).
        
        Thread-switch constraint: Only inject when checkpoint.thread_switch_pending.
        
        Cross-thread scope: Includes goals from all threads for knowledge transfer.
        
        Returns goal briefing markdown string or None (if no thread switch).
        """
```

## Architecture Design

### Module Structure

```
cognition/agent_loop/
├─ goal_context_manager.py (NEW)
├─ state_manager.py (MODIFIED - add flag management)
├─ agent_loop.py (MODIFIED - integrate GoalContextManager)
├─ executor.py (MODIFIED - inject briefing into CoreAgent)
└─ checkpoint.py (MODIFIED - add thread_switch_pending field)
```

### Integration Points

**Plan phase**:

```python
# agent_loop.py - Inject at initialization

async def run_with_progress(...):
    state_manager = AgentLoopStateManager(thread_id, workspace)
    goal_context_manager = GoalContextManager(state_manager, config.goal_context)
    
    # NEW: Inject previous goal context
    plan_goal_excerpts = goal_context_manager.get_plan_context(limit=config.goal_context.plan_limit)
    
    state = LoopState(
        plan_conversation_excerpts=plan_goal_excerpts,  # Changed from []
        ...
    )
    
    # Existing: _build_plan_context uses plan_excerpts
    plan_result = await self.plan_phase.plan(
        goal=goal,
        state=state,
        context=self._build_plan_context(state),  # PlanContext.recent_messages
    )
```

**Execute phase**:

```python
# executor.py - Inject briefing on thread switch

async def execute(self, decision, state):
    goal_context_manager = GoalContextManager(state_manager, config.goal_context)
    
    # NEW: Get goal briefing (only on thread switch)
    goal_briefing = goal_context_manager.get_execute_briefing(limit=config.goal_context.execute_limit)
    
    config = {
        "configurable": {
            "thread_id": state.thread_id,
            "workspace": state.workspace,
            "soothe_goal_briefing": goal_briefing,  # None or markdown string
            ...
        }
    }
    
    # CoreAgent receives briefing in system prompt (existing mechanism)
    async for chunk in self.core_agent.astream(step.description, config=config):
        ...
```

### Thread Switch Detection

**Flag-based mechanism**:

```python
# checkpoint.py - Add flag

class AgentLoopCheckpoint(BaseModel):
    thread_switch_pending: bool = False
    """Flag indicating thread just switched, Execute phase needs goal briefing.
    
    Set by execute_thread_switch(), cleared by get_execute_briefing().
    Ensures goal context injection only on thread switch (not every iteration).
    """

# state_manager.py - Set flag on switch

def execute_thread_switch(self, new_thread_id: str) -> None:
    checkpoint.thread_ids.append(new_thread_id)
    checkpoint.current_thread_id = new_thread_id
    checkpoint.thread_switch_pending = True  # NEW: Set flag
    checkpoint.total_thread_switches += 1
    self.save(checkpoint)
```

## Content Format

### Plan Phase Format

XML blocks for structured reasoning:

```xml
<previous_goal>
Goal: analyze performance bottlenecks in data pipeline
Status: completed
Thread: thread_abc123
Iteration: 3
Duration: 15.2s
Output:
I identified three critical bottlenecks:
1. Database query N+1 problem in user_service.py:142
2. Unbatched API calls in data_fetcher.py:89
3. Missing cache layer for frequently accessed configs

Recommendations implemented:
- Added batch query optimization (reduced 340 queries to 12)
- Implemented request batching with configurable timeout
- Added Redis cache with 5-minute TTL for configs

Performance improved by 67% (baseline: 2.3s → current: 0.76s)
</previous_goal>
```

### Execute Phase Format

Condensed briefing for CoreAgent context:

```
## Previous Goal Context (Thread Switch Recovery)

**Goal 1** (thread_abc123, completed in 3 iterations):
Query: analyze performance bottlenecks in data pipeline
Key findings: Database N+1 queries, unbatched API calls, missing cache
Critical files: user_service.py:142, data_fetcher.py:89
Result: 67% performance improvement (2.3s → 0.76s)

**Goal 2** (thread_def456, completed in 2 iterations):
Query: implement caching strategy for API responses
Key findings: Redis best for session data, CDN for static assets
Critical files: cache_manager.py, api_client.py
Result: 45% latency reduction, 80% backend load decrease

**Current thread**: thread_xyz789 (new thread, no conversation history)
**Instruction**: Use previous goal context to inform step execution strategy.
Reference critical files discovered in prior work. Avoid re-exploring solved problems.
```

### Format Differences

| Aspect | Plan Format | Execute Format |
|--------|-------------|----------------|
| **Structure** | XML blocks | Markdown sections |
| **Detail level** | Full final_report | Condensed summary |
| **Target** | LLM planning decisions | CoreAgent execution |
| **When injected** | Always (every Plan) | Only on thread switch |
| **Thread scope** | Same-thread only | Cross-thread |

## Data Flow

### Scenario 1: First Goal (No History)

```
Checkpoint: goal_history=[], thread_switch_pending=False
├─ Plan: get_plan_context() → [] (no previous goals)
├─ Execute: get_execute_briefing() → None (flag=False)
└─ Clean start (no goal context)
```

### Scenario 2: Same-Thread Continuation

```
Checkpoint: goal_history=[goal1(thread_A)], thread_switch_pending=False
├─ Plan: get_plan_context() → [goal1 XML] (same-thread filter)
│  └─ LLM sees: "Previous: analyze performance → db.py optimized"
├─ Execute: get_execute_briefing() → None (flag=False)
│  └─ CoreAgent already has goal1 conversation in thread state
└─ Goal continuity without duplication
```

### Scenario 3: Thread Switch (RFC-608)

```
Thread switch: thread_A → thread_B
├─ execute_thread_switch() sets thread_switch_pending=True
├─ Plan: get_plan_context() → [] (thread_B has no goals yet)
├─ Execute: get_execute_briefing() → Briefing(goal1 + goal2)
│  └─ Flag=True → Clear flag, generate cross-thread briefing
│  └─ CoreAgent on thread_B receives: "Previous work: db.py optimized..."
└─ Seamless continuation despite lost conversation history
```

## Implementation Details

### GoalContextManager Implementation

```python
class GoalContextManager:
    def __init__(self, state_manager: AgentLoopStateManager, config: GoalContextConfig):
        self._state_manager = state_manager
        self._config = config
    
    def get_plan_context(self, limit: int = 10) -> list[str]:
        checkpoint = self._state_manager.load()
        if not checkpoint or not checkpoint.goal_history:
            return []
        
        # Filter: same-thread + completed only
        current_thread = checkpoint.current_thread_id
        completed_goals = [
            g for g in checkpoint.goal_history
            if g.thread_id == current_thread and g.status == "completed"
        ][-limit:]
        
        # Format as XML blocks
        return [
            f"<previous_goal>\n"
            f"Goal: {g.goal_text}\n"
            f"Status: {g.status}\n"
            f"Thread: {g.thread_id}\n"
            f"Output:\n{g.final_report}\n"
            f"</previous_goal>"
            for g in completed_goals
        ]
    
    def get_execute_briefing(self, limit: int = 10) -> str | None:
        checkpoint = self._state_manager.load()
        if not checkpoint or not checkpoint.thread_switch_pending:
            return None
        
        # Clear flag
        checkpoint.thread_switch_pending = False
        self._state_manager.save(checkpoint)
        
        # Get previous goals (cross-thread)
        previous_goals = [
            g for g in checkpoint.goal_history
            if g.status == "completed"
        ][-limit:]
        
        return self._format_execute_briefing(previous_goals, checkpoint.current_thread_id)
    
    def _format_execute_briefing(self, goals: list, current_thread: str) -> str:
        sections = ["## Previous Goal Context (Thread Switch Recovery)\n\n"]
        
        for i, goal in enumerate(goals, 1):
            key_findings = self._extract_key_findings(goal.final_report)
            critical_files = self._extract_critical_files(goal.final_report)
            result_summary = self._extract_result_summary(goal.final_report)
            
            sections.append(
                f"**Goal {i}** ({goal.thread_id}, {goal.status} in {goal.iteration} iterations):\n"
                f"Query: {goal.goal_text}\n"
                f"Key findings: {key_findings}\n"
                f"Critical files: {critical_files}\n"
                f"Result: {result_summary}\n\n"
            )
        
        sections.append(
            f"**Current thread**: {current_thread} (new thread, no conversation history)\n"
            f"**Instruction**: Use previous goal context to inform step execution strategy.\n"
            f"Reference critical files discovered in prior work. Avoid re-exploring solved problems."
        )
        
        return "".join(sections)
    
    def _extract_key_findings(self, report: str) -> str:
        """Extract first 3 bullet/number items."""
        patterns = [r'^\d+\.\s+(.+)', r'^-\s+(.+)', r'^\*\s+(.+)', ]
        findings = []
        for line in report.split('\n')[:20]:
            for pattern in patterns:
                match = re.match(pattern, line.strip())
                if match:
                    findings.append(match.group(1).strip())
                    if len(findings) >= 3:
                        break
        
        return '; '.join(findings[:3]) if findings else report[:150].rstrip() + "..."
    
    def _extract_critical_files(self, report: str) -> str:
        """Extract file.ext or file.ext:number patterns."""
        pattern = r'\b([a-zA-Z_][a-zA-Z0-9_-]*\.[a-zA-Z]{1,10})(:\d+)?\b'
        matches = re.findall(pattern, report)
        files = [f[0] for f in matches[:5]]
        return ', '.join(files) if files else "None identified"
    
    def _extract_result_summary(self, report: str) -> str:
        """Extract result from 'Result:', 'Outcome:', etc. markers."""
        markers = ['Result:', 'Outcome:', 'Completed:', 'Performance:', 'Summary:']
        for marker in markers:
            if marker in report:
                start = report.find(marker) + len(marker)
                end = report.find('\n', start)
                if end == -1:
                    end = len(report)
                result = report[start:end].strip()
                return result[:100].rstrip() + "..." if len(result) > 100 else result
        
        lines = [l.strip() for l in report.split('\n') if l.strip()]
        return lines[-1][:100].rstrip() + "..." if lines else "Completed"
```

### Checkpoint Modification

```python
class AgentLoopCheckpoint(BaseModel):
    # ... existing fields ...
    
    thread_switch_pending: bool = False
    """Flag indicating thread just switched, Execute phase needs goal briefing.
    
    Set by execute_thread_switch(), cleared by get_execute_briefing().
    Ensures goal context injection only on thread switch (not every iteration).
    """
```

### State Manager Modification

```python
def execute_thread_switch(self, new_thread_id: str) -> None:
    checkpoint.thread_ids.append(new_thread_id)
    checkpoint.current_thread_id = new_thread_id
    checkpoint.thread_switch_pending = True  # NEW
    checkpoint.total_thread_switches += 1
    checkpoint.thread_health_metrics = ThreadHealthMetrics(...)
    self.save(checkpoint)
    
    logger.info(
        "Thread switch executed: loop %s → thread %s (briefing flag set)",
        self.loop_id, new_thread_id,
    )
```

## Configuration

```yaml
agentic:
  goal_context:
    plan_limit: 10  # Number of previous goals for Plan phase
    execute_limit: 10  # Number of previous goals for Execute briefing
    enabled: true  # Enable/disable goal context injection
```

```python
class GoalContextConfig(BaseModel):
    plan_limit: int = Field(default=10, ge=1, le=50)
    execute_limit: int = Field(default=10, ge=1, le=50)
    enabled: bool = Field(default=True)

class AgenticConfig(BaseModel):
    max_iterations: int = DEFAULT_AGENT_LOOP_MAX_ITERATIONS
    prior_conversation_limit: int = 10
    working_memory: WorkingMemoryConfig
    goal_context: GoalContextConfig = Field(default_factory=GoalContextConfig)
```

## Error Handling

**Graceful degradation**:

```python
def get_plan_context(self, limit: int = 10) -> list[str]:
    try:
        checkpoint = self._state_manager.load()
        # ... logic ...
    except Exception as e:
        logger.warning("Failed to load plan context: %s, continuing without goal context", e)
        return []  # Fail gracefully

def get_execute_briefing(self, limit: int = 10) -> str | None:
    try:
        checkpoint = self._state_manager.load()
        # ... logic ...
    except Exception as e:
        logger.error("Failed to generate execute briefing: %s", e)
        return None  # Fail gracefully
```

**Edge cases**:

1. Checkpoint corruption: Return empty context, log warning
2. No completed goals: Empty context ([] or None)
3. Flag stuck True: Retry on next iteration
4. Config disabled: Always return empty context

## Testing Strategy

### Unit Tests

- `test_get_plan_context_filters_same_thread`: Plan context only includes current thread goals
- `test_get_plan_context_filters_completed_only`: Plan context only includes completed goals
- `test_get_execute_briefing_returns_none_without_flag`: Execute briefing requires flag=True
- `test_get_execute_briefing_clears_flag`: Briefing generation clears flag
- `test_get_execute_briefing_cross_thread`: Execute briefing includes all thread goals
- `test_extract_key_findings_bullet_points`: Extraction handles bullet/number formats
- `test_extract_critical_files`: Extraction finds file.py patterns

### Integration Tests

- `test_plan_phase_receives_previous_goal_context`: AgentLoop injects goal context into Plan
- `test_execute_phase_injects_briefing_on_thread_switch`: Thread switch triggers briefing
- `test_execute_phase_no_briefing_same_thread`: Same thread skips briefing

## Performance Considerations

**Memory footprint**:

- Plan context: ~10 blocks × 500 chars = 5KB per iteration
- Execute briefing: ~10 goals × 200 chars = 2KB per thread switch
- Extraction cache: ~50 entries × 300 chars = 15KB (bounded)

**Optimization strategies**:

1. Lazy loading: Generate Plan context once at initialization
2. Early return: Skip briefing if flag=False
3. Bounded cache: Limit extraction cache to 50 reports
4. Configurable limits: Smaller limits for token-sensitive deployments

## Success Criteria

1. **Same-thread continuation**: "translate to chinese" after "analyze performance" correctly translates previous report
2. **Thread switch recovery**: CoreAgent on new thread receives goal summaries, continues work seamlessly
3. **No duplication**: Execute phase doesn't receive briefing when CoreAgent already has conversation history
4. **Architectural isolation**: Goal history stays in loop checkpoint, conversation stays in thread state
5. **Configuration control**: plan_limit/execute_limit/configurable injection

## Implementation Priority

**Phase 1: Core implementation**
1. GoalContextManager module (get_plan_context, get_execute_briefing, extraction methods)
2. Checkpoint modification (thread_switch_pending field)
3. State manager modification (execute_thread_switch flag setting)

**Phase 2: Integration**
4. agent_loop.py integration (inject at initialization)
5. executor.py integration (inject briefing config)
6. Config schema extension (GoalContextConfig)

**Phase 3: Testing and validation**
7. Unit tests for GoalContextManager
8. Integration tests for AgentLoop scenarios
9. End-to-end validation (same-thread, thread-switch)

## Migration Notes

**Backward compatibility**:

- Existing AgentLoop executions: Continue without goal context (no impact)
- Existing checkpoints: thread_switch_pending defaults to False (no change)
- Existing configuration: goal_context defaults to enabled with limit=10

**No breaking changes**: Pure additive feature, opt-in via config.

## References

- RFC-200: Agentic Goal Execution Loop
- RFC-608: AgentLoop Multi-Thread Infinite Lifecycle
- RFC-203: Layer 2 Unified State Model
- CoreAgent context briefing mechanism (existing)