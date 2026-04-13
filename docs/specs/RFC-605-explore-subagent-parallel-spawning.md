# RFC-605: Explore Subagent and Parallel Spawning

**RFC**: 605
**Title**: Explore Subagent and Parallel Spawning
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-13
**Updated**: 2026-04-13
**Dependencies**: RFC-000, RFC-001, RFC-201, RFC-100, RFC-600
**Related**: RFC-211

## Abstract

This RFC introduces two major capabilities to Soothe's AgentLoop architecture:

1. **Explore Subagent**: A specialized subagent for targeted filesystem searches using intelligent wave-based strategies (directory listing → glob patterns → content search), LLM-driven search planning, and match validation with relevance ranking.

2. **Parallel Subagent Spawning**: Extension of AgentLoop's StepAction schema to support multiple concurrent subagent executions via the `subagents` list field, enabling parallel exploration of different filesystem branches or mixed subagent workflows (explore + research running concurrently).

Both features integrate with existing AgentLoop Plan → Execute architecture, leverage deepagents' task tool infrastructure, and maintain thread isolation guarantees.

## Problem Statement

### Current Limitations

1. **Inefficient filesystem navigation**:
   - No specialized agent for targeted searches ("find authentication module")
   - Research subagent is too broad for simple filesystem tasks
   - Direct tool calls (ls, grep) lack intelligence and strategy

2. **Sequential subagent execution only**:
   - StepAction supports single `subagent` field
   - Cannot parallelize filesystem searches across different directories
   - Cannot run explore + research concurrently for comprehensive analysis

3. **Manual subagent selection**:
   - LLMPlanner has limited guidance for choosing subagent type
   - No explicit mapping from goal keywords ("find", "locate") to subagent types

## Design Goals

1. **Intelligent filesystem search** - Wave-based progression with LLM-driven strategy
2. **Parallel execution** - Concurrent subagent spawning for efficiency
3. **Automatic selection** - LLM decides explore usage based on goal characteristics
4. **Clean migration** - Replace `subagent` field with `subagents` list (no backward compatibility)
5. **Thread isolation** - Leverage deepagents' automatic thread branching
6. **Reusability** - Explore uses existing langchain tools (list_files, glob, grep)

## Guiding Principles

1. **Explore as Regular Subagent** - Standard registration in SUBAGENT_FACTORIES, not special execution hint
2. **Wave-Based Efficiency** - Progressive search depth (list → glob → grep) to minimize expensive operations
3. **LLM-Driven Strategy** - Intelligent directory/pattern selection based on search target analysis
4. **Match Validation** - Relevance ranking through LLM assessment, not just filename matching
5. **Parallel via Task Tool** - Leverage deepagents' infrastructure with executor-level coordination
6. **No Backward Compatibility** - Clean schema migration, all code updated to use `subagents` list
7. **Automatic Thread Isolation** - deepagents task tool creates branches per subagent automatically
8. **Wave Cap Enforcement** - Parallel spawns counted toward existing subagent cap

## Architecture

### Explore Subagent Flow

```
┌─────────────────────────────────────────────────────────┐
│  Explore Engine (LangGraph)                              │
│                                                          │
│  START → analyze_target (LLM)                           │
│           ↓ Generate search strategy                    │
│          execute_wave (tool-based)                      │
│           ↓ Wave 1/2/3 progression                      │
│          should_continue_search? (conditional)          │
│           ↓ Yes → execute_wave                          │
│           ↓ No → validate_matches (LLM)                 │
│          synthesize_results                             │
│           ↓ Format top matches                          │
│  END                                                     │
└─────────────────────────────────────────────────────────┘
```

**Wave Progression**:
- **Wave 1**: List high-probability directories (priority_dirs from strategy)
- **Wave 2**: Glob patterns in workspace (file_patterns from strategy)
- **Wave 3**: Grep content search (content_keywords from strategy, last resort)

**Conditional Edge**: Continue if wave < max_waves AND candidates < threshold

### Parallel Subagent Spawning Flow

```
StepAction(subagents=["explore", "research"])
  ↓
Executor._execute_step_collecting_events()
  ↓
Build combined prompt: "Execute these subagent delegations in parallel:"
  ↓
CoreAgent.astream() → LLM makes N task tool calls (parallel tool calling)
  ↓
deepagents SubAgentMiddleware:
  - Thread branch: {thread_id}__task_{uuid1} for explore
  - Thread branch: {thread_id}__task_{uuid2} for research
  ↓
Executor aggregates ToolMessages → single StepResult
  ↓
Outcome: {type: "parallel_subagents", subagents: [...], outputs: [...]}
```

### Integration with AgentLoop Plan Phase

**LLMPlanner Prompt Enhancement**:

```xml
<AVAILABLE_SUBAGENTS>
- browser: Web automation
- research: Multi-source synthesis
- claude: Full capabilities
- explore: Targeted filesystem search (NEW)

<SUBAGENT_SELECTION_GUIDE>
- "Find authentication module" → subagents=["explore"]
- "Locate API endpoints" → subagents=["explore"]
- "Search src/ and tests/ concurrently" → subagents=["explore", "explore"]
- "Explore filesystem + research online" → subagents=["explore", "research"]
</SUBAGENT_SELECTION_GUIDE>
</AVAILABLE_SUBAGENTS>
```

**Plan Output Examples**:

```json
// Single explore
{
  "steps": [{
    "subagents": ["explore"],
    "description": "Find authentication module"
  }]
}

// Parallel explores
{
  "steps": [{
    "subagents": ["explore", "explore"],
    "execution_mode": "parallel",
    "description": "Search src/ and tests/ concurrently"
  }]
}

// Mixed parallel
{
  "steps": [{
    "subagents": ["explore", "research"],
    "execution_mode": "parallel",
    "description": "Explore filesystem and research patterns online"
  }]
}
```

## Specification

### 1. Explore Subagent Implementation

#### 1.1 ExploreState Schema

```python
class ExploreState(TypedDict):
    messages: Annotated[list, add_messages]
    search_target: str              # What we're searching for
    workspace: str                  # Search boundary
    search_strategy: dict           # LLM-generated plan
    search_waves: list[dict]        # Wave execution history
    candidates: list[str]           # Found file paths
    validated_matches: list[dict]   # Ranked results with relevance
    current_wave: int               # Wave counter
    max_waves: int                  # Depth limit (default 3)
```

#### 1.2 Search Strategy Schema

```python
class SearchStrategy(BaseModel):
    priority_dirs: list[str]        # 3-5 high-probability directories
    file_patterns: list[str]        # Glob patterns matching target
    content_keywords: list[str]     # Keywords for grep (last resort)
    search_type: str                # "code", "config", "docs", "general"
```

#### 1.3 Explore Engine Nodes

**analyze_target_node**:
- Input: search_target, workspace
- Process: LLM structured output → SearchStrategy
- Output: search_strategy dict, current_wave=1, search_waves=[]
- LLM analyzes target intent, generates intelligent directory/pattern hints

**execute_wave_node**:
- Input: search_strategy, current_wave, workspace
- Process: Wave-based execution
  - Wave 1: `list_files` in priority_dirs
  - Wave 2: `glob` with file_patterns
  - Wave 3: `grep` with content_keywords
- Output: search_waves updated, candidates appended, current_wave incremented
- Uses langchain tools: list_files, glob, grep (no custom implementations)

**validate_matches_node**:
- Input: candidates (limit 20), search_target
- Process: LLM reads snippets (first 500 chars), assesses relevance
- Output: validated_matches with relevance ranking ("high", "medium", "low")
- Returns top 5 matches with brief descriptions

**synthesize_results_node**:
- Input: validated_matches
- Process: Format final output with file paths + descriptions
- Output: AIMessage with top 3-5 matches
- Emits ExploreCompletedEvent

#### 1.4 Conditional Edge Logic

```python
def should_continue_search(state: ExploreState) -> str:
    """Continue if wave < max_waves AND candidates insufficient."""

    if state['current_wave'] > state['max_waves']:
        return "validate"

    if len(state['candidates']) >= 20:
        return "validate"

    return "continue"
```

#### 1.5 Factory Function

```python
def create_explore_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledSubAgent:
    """Create explore subagent.

    Args:
        model: LLM for strategy/validation
        config: Soothe configuration
        context: workspace, max_waves settings

    Returns:
        CompiledSubAgent dict with name, description, runnable
    """
    runnable = build_explore_engine(model, ExploreConfig(max_waves=3))

    return {
        "name": "explore",
        "description": (
            "Targeted filesystem search agent for efficiently finding specific files, "
            "modules, or patterns. Uses intelligent wave-based search strategy: "
            "directory listing → glob patterns → content search. Validates matches "
            "with LLM ranking. Use when goal mentions 'find', 'locate', 'search for', "
            "or requires navigating filesystem toward a specific target."
        ),
        "runnable": runnable,
    }
```

#### 1.6 Events

```python
class ExploreStrategyEvent(SootheEvent):
    type: str = "soothe.subagents.explore.strategy"
    search_target: str
    priority_dirs: list[str]
    file_patterns: list[str]

class ExploreWaveEvent(SootheEvent):
    type: str = "soothe.subagents.explore.wave"
    wave_number: int
    method: str  # "list_files", "glob", "grep"
    files_found: int

class ExploreMatchEvent(SootheEvent):
    type: str = "soothe.subagents.explore.match"
    file_path: str
    relevance: str  # "high", "medium", "low"
    description: str

class ExploreCompletedEvent(SootheEvent):
    type: str = "soothe.subagents.explore.completed"
    total_candidates: int
    top_matches: list[dict]
    waves_executed: int
```

### 2. StepAction Schema Migration

#### 2.1 Schema Change

**Remove backward compatibility** - replace single field with list:

```python
class StepAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tools: list[str] | None = None
    subagents: list[str] | None = None  # NEW: list of 1 or N
    expected_output: str
    dependencies: list[str] | None = None
```

**No validation** - single field handles both cases naturally.

#### 2.2 Migration Impact

**Breaking changes** (no backward compatibility):

- All existing StepAction instantiations must update
- `subagent="browser"` → `subagents=["browser"]`
- `subagent="research"` → `subagents=["research"]`

**Files requiring updates**:
- `src/soothe/cognition/agent_loop/schemas.py`
- `src/soothe/cognition/agent_loop/executor.py`
- `src/soothe/cognition/agent_loop/planner.py`
- All test files with StepAction usage

### 3. Parallel Spawning Implementation

#### 3.1 Executor Routing Logic

```python
async def _execute_step_collecting_events(self, step: StepAction, ...):
    """Route based on subagents list length."""

    if step.subagents:
        if len(step.subagents) == 1:
            return await self._execute_single_subagent_via_task(step, ...)
        else:
            return await self._execute_parallel_subagents_via_task(step, ...)
```

#### 3.2 Parallel Execution Method

```python
async def _execute_parallel_subagents_via_task(
    self,
    step: StepAction,
    thread_id: str,
    workspace: str | None,
) -> tuple[list[StreamEvent], StepResult]:
    """Execute multiple subagents via parallel task tool calls.

    CoreAgent receives combined prompt, LLM outputs N task tool calls,
    deepagents executes them concurrently via asyncio.gather.

    Returns:
        Tuple of (events, StepResult with aggregated outcomes)
    """
    # Build combined prompt
    subagent_calls = [
        f"{i+1}. Use {name} subagent for: {step.description}"
        for i, name in enumerate(step.subagents)
    ]
    combined_prompt = "Execute in parallel:\n" + "\n".join(subagent_calls)

    # Stream execution
    stream = self.core_agent.astream(
        {"messages": [HumanMessage(content=combined_prompt)]},
        config={"configurable": {
            "thread_id": thread_id,
            "workspace": workspace,
            "parallel_subagent_execution": True,
        }},
        stream_mode=["messages", "updates", "custom"],
        subgraphs=True,
    )

    # Collect events and outcomes
    events: list[StreamEvent] = []
    subagent_results: list[str] = []
    tool_call_count = 0

    async for output, event, tc_count, _msgs in self._stream_and_collect(stream):
        if event:
            events.append(event)
        elif output:
            subagent_results.append(output)
            tool_call_count = tc_count

    # Aggregate outcomes
    combined_outcome = {
        "type": "parallel_subagents",
        "subagents": step.subagents,
        "size_bytes": sum(len(r) for r in subagent_results),
        "outputs": subagent_results,
    }

    return events, StepResult(
        step_id=step.id,
        success=True,
        outcome=combined_outcome,
        duration_ms=...,
        thread_id=thread_id,
        tool_call_count=tool_call_count,
        subagent_task_completions=len(step.subagents),  # Count toward cap
        hit_subagent_cap=False,
    )
```

#### 3.3 Thread Isolation Mechanism

**Automatic via deepagents task tool**:
- Each task invocation creates thread branch: `{thread_id}__task_{uuid}`
- Parallel spawns get independent branches
- Parent thread_id used for CoreAgent call
- Thread safety via langgraph's atomic state updates

#### 3.4 Wave Cap Enforcement

```python
# In _stream_and_collect (existing logic enhanced)
budget.max_subagent_tasks_per_wave = config.agentic.max_subagent_tasks_per_wave

# Each ToolMessage from task tool increments budget.subagent_task_completions
# Parallel spawn of N subagents = N toward cap
# Stops stream if cap exceeded mid-execution
```

### 4. Configuration Schema

```yaml
subagents:
  explore:
    enabled: true
    model_role: "default"
    max_waves: 3
    validation_threshold: "medium"
    max_candidates_per_wave: 20

agentic:
  max_parallel_steps: 3
  max_subagent_tasks_per_wave: 2  # Cap applies to parallel spawns

  parallel_subagent_execution:
    enabled: true
    max_concurrent_subagents: 3
    timeout_per_subagent: 120
    aggregate_mode: "concatenate"  # How to combine outputs
```

### 5. Subagent Registry

```python
# In src/soothe/core/resolver/_resolver_tools.py

from soothe.subagents.explore.implementation import create_explore_subagent

SUBAGENT_FACTORIES = {
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
    "research": create_research_subagent,
    "explore": create_explore_subagent,  # NEW
}
```

### 6. LLMPlanner Integration

```python
# In _build_plan_prompt (planner.py)

sections.append("""
<AVAILABLE_SUBAGENTS>
- browser: Web automation and browsing tasks
- research: Multi-source research and synthesis
- claude: General-purpose agent with full capabilities
- explore: Targeted filesystem search and navigation

<SUBAGENT_SELECTION_GUIDE>
- "Find authentication module" → subagents=["explore"]
- "Search src/ and tests/ concurrently" → subagents=["explore", "explore"]
- "Explore filesystem + research online" → subagents=["explore", "research"]
</SUBAGENT_SELECTION_GUIDE>
</AVAILABLE_SUBAGENTS>
""")
```

## Implementation Status

- ⚠️ Explore subagent engine (pending implementation)
- ⚠️ Explore factory function (pending)
- ⚠️ Explore events (pending)
- ⚠️ StepAction schema migration (pending)
- ⚠️ Executor parallel spawning logic (pending)
- ⚠️ LLMPlanner prompt enhancement (pending)
- ⚠️ Configuration schema (pending)
- ⚠️ Subagent registry update (pending)

## Testing Requirements

### Unit Tests

1. **Explore subagent**:
   - Strategy generation (mock LLM)
   - Wave execution logic (mock tools)
   - Match validation/ranking
   - Conditional edge decisions

2. **Schema**:
   - StepAction with single vs multiple subagents

3. **Executor**:
   - Single subagent routing
   - Parallel spawning mechanics
   - Outcome aggregation
   - Wave cap enforcement

### Integration Tests

1. **Explore end-to-end**:
   - Single explore execution
   - Wave progression
   - Match quality

2. **Parallel execution**:
   - Two explore subagents concurrently
   - Three explores (max concurrent)
   - Mixed (explore + research)
   - Thread isolation verification

3. **AgentLoop integration**:
   - LLM auto-selects explore
   - Parallel execution modes
   - Metrics aggregation
   - Wave cap stops excessive spawns

## Migration Checklist

1. Create `src/soothe/subagents/explore/` package
2. Update `schemas.py` - replace `subagent` with `subagents`
3. Update `executor.py` - add parallel spawning logic
4. Update `planner.py` - enhance prompts
5. Update `resolver/_resolver_tools.py` - register explore
6. Update all tests with StepAction usage
7. Add explore configuration to `config.yml`
8. Run `./scripts/verify_finally.sh`

## Security Considerations

1. **Thread isolation** - Automatic via deepagents task tool
2. **Workspace boundary** - Explore inherits workspace ContextVar from parent
3. **Permission inheritance** - Subagents inherit narrowed permission set from parent
4. **Wave cap** - Prevents runaway parallel spawning

## Performance Considerations

1. **Wave-based efficiency** - Minimizes expensive grep operations
2. **Parallel execution** - Concurrent searches reduce wall-clock time
3. **Candidate limiting** - Max 20 candidates for validation (efficiency)
4. **LLM token efficiency** - Wave 1/2 are tool-only, Wave 3 uses LLM for validation

## Related Documents

- RFC-201: AgentLoop architecture
- RFC-211: Layer 2 tool result optimization
- RFC-600: Plugin extension system
- Design draft: `docs/drafts/2026-04-13-explore-subagent-parallel-spawning-design.md`

## Changelog

### 2026-04-13
- Initial RFC draft from approved design
- Two major capabilities: explore subagent + parallel spawning
- Breaking schema change (no backward compatibility)
- Integration with AgentLoop Plan → Execute architecture

---

*Explore subagent for intelligent filesystem search + parallel subagent spawning for concurrent execution.*