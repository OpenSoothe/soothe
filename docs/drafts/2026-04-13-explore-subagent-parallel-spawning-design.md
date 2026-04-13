# Design Draft: Explore Subagent with Parallel Spawning

**Date**: 2026-04-13
**Author**: Claude (Platonic Brainstorming)
**Status**: Draft for user review
**Next Stage**: Platonic Coding Phase 1 RFC formalization

---

## Overview

Design an **explore subagent** for targeted filesystem searches (similar to Claude Code CLI) with intelligent search strategies, and extend AgentLoop to support **parallel subagent spawning** for concurrent execution of multiple subagents.

### Key Requirements

1. **Explore subagent**: Efficient filesystem navigation toward specific targets (e.g., "find authentication module", "locate API endpoints")
2. **LLM-driven auto-selection**: AgentLoop Plan phase automatically decides when to use explore vs direct tools
3. **Parallel spawning**: Execute multiple subagents concurrently (multiple explores, or mixed explore+research)

---

## Design Section 1: Explore Subagent Architecture

### Purpose

Specialized subagent for **targeted filesystem searches** - efficiently navigating file tree toward specific targets. More focused than research subagent, more intelligent than direct tool calls.

### Core Design

**Type**: `CompiledSubAgent` (like browser/research)

**Runnable**: LangGraph with intelligent search strategy:

```
┌─────────────────────────────────────────────────────────┐
│  Explore Engine (LangGraph)                              │
│                                                          │
│  1. Analyze target (LLM) → search strategy              │
│     - Parse goal: "find X", "locate Y", "search for Z"   │
│     - Generate search plan: directory hints, patterns    │
│                                                          │
│  2. Execute search waves (tool-based)                    │
│     - Wave 1: High-probability directories              │
│     - Wave 2: Medium-probability (if needed)            │
│     - Wave 3: Full scan (last resort)                   │
│                                                          │
│  3. Validate matches (LLM)                               │
│     - Check if found files match target intent           │
│     - Rank by relevance                                  │
│                                                          │
│  4. Synthesize results                                   │
│     - Return top matches with context                    │
│     - Include file paths + brief descriptions            │
└─────────────────────────────────────────────────────────┘
```

**State Schema**:

```python
class ExploreState(TypedDict):
    messages: Annotated[list, add_messages]
    search_target: str          # What we're searching for
    workspace: str              # Search boundary
    search_strategy: dict       # LLM-generated plan
    search_waves: list[dict]    # Wave execution history
    candidates: list[str]       # Found file paths
    validated_matches: list[dict]  # Ranked results with relevance
    current_wave: int           # Wave counter
    max_waves: int              # Depth limit (config)
```

### Key Features

1. **Intelligent routing**: Uses LLM to parse goal and choose search strategy
   - Code search: prioritize `src/`, `lib/`, look for `.py`, `.js` files
   - Config search: prioritize root, `config/`, look for `.yml`, `.json`
   - Doc search: prioritize `docs/`, `README*`, `.md` files

2. **Wave-based execution**: Progressive search depth
   - Wave 1: `list_files` in high-probability dirs
   - Wave 2: `glob` patterns based on target type
   - Wave 3: `grep` content search (expensive, last resort)

3. **Match validation**: LLM checks if candidates match intent
   - "Find auth module" → LLM reads candidates, ranks by relevance
   - Returns top 3-5 matches with brief descriptions

4. **State isolation**: Inherits workspace ContextVar from parent thread

---

## Design Section 2: Multi-Subagent Support

### StepAction Schema Change

**Remove backward compatibility** - replace single `subagent` field with `subagents` list:

```python
class StepAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tools: list[str] | None = None
    subagents: list[str] | None = None  # Multi-subagent support (list of 1 or N)
    expected_output: str
    dependencies: list[str] | None = None
```

**No validation needed** - single field handles both single and parallel cases.

### Example Plan Outputs

**Single explore**:
```json
{
  "steps": [{
    "id": "S_1",
    "description": "Find authentication module",
    "execution_hint": "subagent",
    "subagents": ["explore"]
  }]
}
```

**Parallel explores** (different directories):
```json
{
  "steps": [{
    "id": "S_1",
    "description": "Search src/ and tests/ concurrently",
    "execution_hint": "subagent",
    "subagents": ["explore", "explore"],
    "execution_mode": "parallel"
  }]
}
```

**Mixed parallel** (explore + research):
```json
{
  "steps": [{
    "id": "S_1",
    "description": "Explore filesystem and research online patterns",
    "execution_hint": "subagent",
    "subagents": ["explore", "research"],
    "execution_mode": "parallel"
  }]
}
```

### Executor Routing Logic

```python
async def _execute_step_collecting_events(self, step: StepAction, ...):
    if step.subagents:
        if len(step.subagents) == 1:
            # Single subagent: direct task tool call
            subagent_name = step.subagents[0]
            step_body = f"Using {subagent_name} subagent: {step.description}"
        else:
            # Multiple subagents: parallel spawning
            subagent_list = ", ".join(step.subagents)
            step_body = f"Using {subagent_list} in parallel: {step.description}"
            # asyncio.gather to spawn all via task tool
```

### Subagent Registry

Explore added as standard subagent to factory registry:

```python
SUBAGENT_FACTORIES = {
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
    "research": create_research_subagent,
    "explore": create_explore_subagent,  # NEW
}
```

### LLMPlanner Prompt Enhancement

```xml
<AVAILABLE_SUBAGENTS>
- browser: Web automation and browsing tasks
- research: Multi-source research and synthesis
- claude: General-purpose agent with full capabilities
- explore: Targeted filesystem search and navigation (NEW)

<SUBAGENT_SELECTION_GUIDE>
- "Find authentication module" → subagents=["explore"]
- "Research async patterns" → subagents=["research"]
- "Browse to GitHub" → subagents=["browser"]
- "Explore filesystem and research online" → subagents=["explore", "research"]
</SUBAGENT_SELECTION_GUIDE>
</AVAILABLE_SUBAGENTS>
```

---

## Design Section 3: Parallel Subagent Spawning Mechanics

### Execution Strategy

**Option A: Multiple task tool calls in one wave** (Selected approach)

- Executor calls `task` tool N times for N subagents
- Uses asyncio.gather to execute all tool calls concurrently
- Each task tool invocation creates isolated thread branch automatically
- Works with existing deepagents infrastructure

### Implementation Flow

```
StepAction(subagents=["explore", "research"])
  ↓
Executor._execute_step_collecting_events()
  ↓
Detect step.subagents has length > 1
  ↓
Build N task tool invocations:
  [
    HumanMessage("task(description='Explore src/ for auth', subagent_type='explore')"),
    HumanMessage("task(description='Research auth patterns', subagent_type='research')")
  ]
  ↓
Pass to CoreAgent.astream() with combined prompt
  ↓
CoreAgent makes N tool calls in single LLM turn (parallel tool calling)
  ↓
deepagents SubAgentMiddleware handles each task call:
  - Creates isolated thread branches
  - Invokes each subagent runnable
  - Returns ToolMessage per subagent
  ↓
Executor collects all ToolMessages
  ↓
Aggregate into single StepResult with combined outcomes
```

### Executor Implementation

```python
async def _execute_parallel_subagents(
    self,
    step: StepAction,
    thread_id: str,
    workspace: str | None,
) -> tuple[list[StreamEvent], StepResult]:
    """Execute multiple subagents via parallel task tool calls.

    CoreAgent receives combined prompt instructing it to call
    task tool N times. LLM's parallel tool calling capability
    handles concurrent execution.
    """
    start = time.perf_counter()
    events: list[StreamEvent] = []
    outcomes: list[dict] = []

    # Build combined prompt for parallel task calls
    subagent_calls = []
    for i, subagent_name in enumerate(step.subagents):
        call_desc = f"{i+1}. Use {subagent_name} subagent for: {step.description}"
        subagent_calls.append(call_desc)

    combined_prompt = "Execute these subagent delegations in parallel:\n" + "\n".join(subagent_calls)

    # Stream execution
    configurable = {
        "thread_id": thread_id,
        "workspace": workspace,
        "parallel_subagent_execution": True,
    }

    stream = self.core_agent.astream(
        {"messages": [HumanMessage(content=combined_prompt)]},
        config={"configurable": configurable},
        stream_mode=["messages", "updates", "custom"],
        subgraphs=True,
    )

    # Collect events and outcomes from all task tool calls
    tool_call_count = 0
    subagent_results: list[str] = []

    async for final_output, event, tc_count, _msg_list in self._stream_and_collect(stream):
        if event is not None:
            events.append(event)
        elif final_output is not None:
            tool_call_count = tc_count
            subagent_results.append(final_output)

    duration_ms = int((time.perf_counter() - start) * 1000)

    # Aggregate outcomes from all subagents
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
        duration_ms=duration_ms,
        thread_id=thread_id,
        tool_call_count=tool_call_count,
        subagent_task_completions=len(step.subagents),
        hit_subagent_cap=False,
    )
```

### Key Design Points

1. **LLM Parallel Tool Calling**: Modern LLMs (GPT-4, Claude) support calling multiple tools in single response
   - CoreAgent receives prompt: "Execute these subagent delegations in parallel..."
   - LLM outputs N `task` tool calls in one AIMessage
   - deepagents executes them concurrently via asyncio.gather internally

2. **Automatic Thread Isolation**: deepagents task tool creates thread branches:
   - `{thread_id}__task_{uuid1}` for first subagent
   - `{thread_id}__task_{uuid2}` for second subagent
   - Parent thread_id used for CoreAgent call, branches isolated

3. **Outcome Aggregation**: Combine all subagent results into single StepResult:
   - `subagent_task_completions`: Count of spawned subagents
   - `outcome.outputs`: List of individual subagent outputs
   - Single step_id credited for entire parallel wave

4. **Wave Cap Enforcement**: Existing cap logic still applies:
   - `max_subagent_tasks_per_wave`: Counts total spawned subagents
   - Parallel spawn of 3 subagents = 3 toward cap
   - Stops stream if cap exceeded mid-execution

---

## Design Section 4: Explore Subagent Implementation Details

### Explore Engine Architecture (LangGraph)

```python
def build_explore_engine(model: BaseChatModel, config: ExploreConfig) -> CompiledStateGraph:
    """Build explore subagent runnable.

    Nodes:
    1. analyze_target: Parse search intent, generate strategy
    2. execute_wave: Run file operations (list/glob/grep)
    3. validate_matches: LLM checks candidates against target
    4. synthesize_results: Format final output

    Conditional edges based on wave depth and match quality.
    """
    graph = StateGraph(ExploreState)

    graph.add_node("analyze_target", analyze_target_node)
    graph.add_node("execute_wave", execute_wave_node)
    graph.add_node("validate_matches", validate_matches_node)
    graph.add_node("synthesize_results", synthesize_results_node)

    graph.add_edge(START, "analyze_target")
    graph.add_edge("analyze_target", "execute_wave")
    graph.add_conditional_edges(
        "execute_wave",
        should_continue_search,
        {
            "continue": "execute_wave",  # More waves if needed
            "validate": "validate_matches",
        }
    )
    graph.add_edge("validate_matches", "synthesize_results")
    graph.add_edge("synthesize_results", END)

    return graph.compile()
```

### Search Strategy Generation (analyze_target node)

```python
async def analyze_target_node(state: ExploreState) -> dict:
    """LLM analyzes search target and generates intelligent strategy.

    Examples:
    - "Find authentication module" → strategy: {"priority_dirs": ["src/auth", "lib/auth"], "patterns": ["*auth*.py"]}
    - "Locate API endpoints" → strategy: {"priority_dirs": ["src/api", "routes"], "patterns": ["endpoint*.py"]}
    - "Search for config files" → strategy: {"priority_dirs": ["config", "."], "patterns": ["*.yml", "*.json"]}
    """
    strategy_prompt = f"""Analyze this search target and generate an efficient filesystem search strategy.

Target: {state['search_target']}
Workspace: {state['workspace']}

Generate a JSON search strategy with:
1. priority_dirs: List of 3-5 high-probability directories to search first
2. file_patterns: Glob patterns likely to match the target
3. content_keywords: Keywords for content search (last resort)
4. search_type: "code", "config", "docs", or "general"
"""

    structured_model = model.with_structured_output(SearchStrategy)
    strategy = await structured_model.ainvoke([HumanMessage(content=strategy_prompt)])

    return {
        "search_strategy": strategy.dict(),
        "current_wave": 1,
        "search_waves": [],
    }
```

### Wave Execution (execute_wave_node)

```python
async def execute_wave_node(state: ExploreState) -> dict:
    """Execute search wave based on current strategy.

    Wave progression:
    - Wave 1: List files in priority directories
    - Wave 2: Glob patterns in priority dirs + broad dirs
    - Wave 3: Grep content search (expensive, last resort)

    Uses langchain tools: list_files, glob, grep
    """
    strategy = state['search_strategy']
    wave = state['current_wave']
    workspace = state['workspace']

    wave_results = []

    if wave == 1:
        # Wave 1: List high-probability directories
        for dir_path in strategy['priority_dirs']:
            result = await list_files_tool.ainvoke({"path": f"{workspace}/{dir_path}"})
            wave_results.append({
                "method": "list_files",
                "path": dir_path,
                "files": result,
            })

    elif wave == 2:
        # Wave 2: Glob patterns
        for pattern in strategy['file_patterns']:
            result = await glob_tool.ainvoke({"pattern": pattern, "path": workspace})
            wave_results.append({
                "method": "glob",
                "pattern": pattern,
                "files": result,
            })

    elif wave == 3:
        # Wave 3: Content search (last resort)
        for keyword in strategy['content_keywords']:
            result = await grep_tool.ainvoke({"pattern": keyword, "path": workspace})
            wave_results.append({
                "method": "grep",
                "keyword": keyword,
                "files": result,
            })

    new_candidates = extract_files_from_wave_results(wave_results)

    return {
        "search_waves": state['search_waves'] + [wave_results],
        "candidates": state['candidates'] + new_candidates,
        "current_wave": wave + 1,
    }
```

### Match Validation (validate_matches_node)

```python
async def validate_matches_node(state: ExploreState) -> dict:
    """LLM validates and ranks candidates against search target.

    Reads candidate files, checks relevance, ranks by match quality.
    Returns top 3-5 matches with brief descriptions.
    """
    candidates = state['candidates']
    target = state['search_target']

    # Read content snippets from candidates (use read_file tool)
    candidate_snippets = []
    for file_path in candidates[:20]:  # Limit to top 20 for efficiency
        content = await read_file_tool.ainvoke({"file_path": file_path, "limit": 50})
        candidate_snippets.append({
            "path": file_path,
            "snippet": content[:500],
        })

    validation_prompt = f"""Validate these candidate files against the search target.

Target: {target}

Candidates:
{format_candidates(candidate_snippets)}

For each candidate, assess:
1. relevance: "high", "medium", "low", or "none"
2. reason: Brief explanation why it matches or doesn't

Return top 5 matches with relevance ranking.
"""

    structured_model = model.with_structured_output(ValidationResult)
    validation = await structured_model.ainvoke([HumanMessage(content=validation_prompt)])

    return {
        "validated_matches": validation.matches,
    }
```

### Conditional Edge Logic

```python
def should_continue_search(state: ExploreState) -> str:
    """Decide whether to continue searching or validate current matches.

    Continue if:
    - Wave < max_waves (default 3)
    - No high-relevance matches found yet
    - Candidates list is small (< 10)

    Validate if:
    - Reached max_waves
    - Found sufficient candidates (> 20)
    - Found at least one high-relevance match in earlier waves
    """
    wave = state['current_wave']
    max_waves = state['max_waves']
    candidates_count = len(state['candidates'])

    if wave > max_waves:
        return "validate"

    if candidates_count >= 20:
        return "validate"

    return "continue"
```

### Explore Subagent Factory

```python
def create_explore_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledSubAgent:
    """Create explore subagent.

    Args:
        model: LLM for strategy generation and validation
        config: Soothe configuration
        context: Context with workspace, max_waves settings

    Returns:
        CompiledSubAgent dict with name, description, runnable
    """
    workspace = context.get("work_dir", "")
    max_waves = context.get("max_waves", 3)

    explore_config = ExploreConfig(max_waves=max_waves)
    runnable = build_explore_engine(model, explore_config)

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

---

## Design Section 5: Configuration and System Integration

### Configuration Schema

```yaml
# In src/soothe/config/config.yml

subagents:
  # Existing subagents
  browser:
    enabled: true
    model_role: "default"

  research:
    enabled: true
    model_role: "default"
    sources: ["web", "academic"]
    max_loops: 3

  claude:
    enabled: true
    model_role: "default"

  # NEW: Explore subagent configuration
  explore:
    enabled: true
    model_role: "default"
    max_waves: 3
    validation_threshold: "medium"
    max_candidates_per_wave: 20

agentic:
  max_iterations: 8
  max_parallel_steps: 3
  max_subagent_tasks_per_wave: 2

  # NEW: Parallel subagent spawning settings
  parallel_subagent_execution:
    enabled: true
    max_concurrent_subagents: 3
    timeout_per_subagent: 120
    aggregate_mode: "concatenate"
```

### Events

```python
# In src/soothe/subagents/explore/events.py

class ExploreStrategyEvent(SootheEvent):
    """Explore subagent generated search strategy."""
    type: str = "soothe.subagents.explore.strategy"
    search_target: str
    priority_dirs: list[str]
    file_patterns: list[str]

class ExploreWaveEvent(SootheEvent):
    """Explore wave execution completed."""
    type: str = "soothe.subagents.explore.wave"
    wave_number: int
    method: str
    files_found: int
    candidates_added: int

class ExploreMatchEvent(SootheEvent):
    """Explore validated match."""
    type: str = "soothe.subagents.explore.match"
    file_path: str
    relevance: str
    description: str

class ExploreCompletedEvent(SootheEvent):
    """Explore subagent finished."""
    type: str = "soothe.subagents.explore.completed"
    total_candidates: int
    top_matches: list[dict]
    waves_executed: int

# Register events
register_event(ExploreStrategyEvent, summary_template="Strategy: {search_target} → {priority_dirs}")
register_event(ExploreWaveEvent, summary_template="Wave {wave_number}: {method} found {files_found} files")
register_event(ExploreMatchEvent, summary_template="Match: {file_path} ({relevance})")
register_event(ExploreCompletedEvent, summary_template="Found {total_candidates} candidates, {waves_executed} waves")
```

### Executor Integration Points

```python
# In executor.py

# Point 1: Detect multi-subagent steps
async def _execute_step_collecting_events(self, step: StepAction, ...):
    if step.subagents:
        if len(step.subagents) == 1:
            return await self._execute_single_subagent_via_task(step, ...)
        else:
            return await self._execute_parallel_subagents_via_task(step, ...)

# Point 2: Track parallel subagent completions for wave cap
budget.max_subagent_tasks_per_wave = config.agentic.max_subagent_tasks_per_wave
# Each spawned subagent increments budget.subagent_task_completions

# Point 3: Aggregate parallel outcomes
combined_outcome = {
    "type": "parallel_subagents",
    "subagents": step.subagents,
    "outputs": [...],
    "aggregate_mode": config.agentic.parallel_subagent_execution.aggregate_mode,
}
```

---

## Implementation Plan

### Phase 1: Explore Subagent Core

1. Create `src/soothe/subagents/explore/` package structure
2. Implement `engine.py` with LangGraph nodes
3. Implement `implementation.py` factory function
4. Define events and schemas
5. Add unit tests for explore logic

### Phase 2: StepAction Schema Migration

1. Update `schemas.py` - replace `subagent` with `subagents` list
2. Update all existing code using StepAction
3. Update test instantiations
4. Verify no backward compatibility remnants

### Phase 3: Parallel Spawning Implementation

1. Implement `_execute_parallel_subagents_via_task()` in executor
2. Add parallel aggregation logic
3. Update wave cap tracking for parallel spawns
4. Add integration tests for parallel execution

### Phase 4: LLMPlanner Integration

1. Update `_build_plan_prompt()` with subagent selection guide
2. Update plan generation logic to use `subagents` field
3. Test LLM auto-selection for explore scenarios

### Phase 5: Configuration and Registration

1. Add explore config schema to `config.yml`
2. Register explore factory in `SUBAGENT_FACTORIES`
3. Update documentation

---

## Testing Strategy

### Unit Tests

1. **Explore subagent tests**:
   - Strategy generation (mock LLM responses)
   - Wave execution logic (mock file tools)
   - Match validation and ranking
   - Conditional edge decisions

2. **Schema tests**:
   - StepAction validation (single vs multiple subagents)
   - Plan generation with `subagents` field

3. **Executor tests**:
   - Single subagent routing
   - Parallel subagent spawning mechanics
   - Outcome aggregation logic
   - Wave cap enforcement with parallel spawns

### Integration Tests

1. **Explore end-to-end**:
   - Single explore subagent execution
   - Search strategy validation
   - Wave progression
   - Match quality assessment

2. **Parallel execution**:
   - Two explore subagents concurrently
   - Three explore subagents (max concurrent)
   - Mixed parallel (explore + research)
   - Thread isolation verification

3. **AgentLoop integration**:
   - LLM auto-selects explore for "find X" goals
   - Parallel execution modes work correctly
   - Metrics aggregation from parallel subagents
   - Wave cap stops excessive parallel spawns

### Migration Tests

- All existing StepAction usages updated
- No references to old `subagent` field
- Backward compatibility completely removed

---

## Migration Impact

### Breaking Changes

1. **StepAction schema**:
   - Remove: `subagent: str | None`
   - Add: `subagents: list[str] | None`
   - All code must update: `subagent="X"` → `subagents=["X"]`

2. **Files requiring updates**:
   - `src/soothe/cognition/agent_loop/schemas.py`
   - `src/soothe/cognition/agent_loop/executor.py`
   - `src/soothe/cognition/agent_loop/planner.py`
   - `src/soothe/core/resolver/_resolver_tools.py`
   - All test files with StepAction instantiations

3. **New modules to create**:
   - `src/soothe/subagents/explore/__init__.py`
   - `src/soothe/subagents/explore/engine.py`
   - `src/soothe/subagents/explore/implementation.py`
   - `src/soothe/subagents/explore/events.py`
   - `src/soothe/subagents/explore/schemas.py`

### No Backward Compatibility

As requested, this design removes backward compatibility completely. All existing code must be migrated to use the new `subagents` field.

---

## Key Design Decisions Summary

1. **Explore as regular subagent** - Not a special execution hint, registered in standard factory
2. **Multi-subagent via list field** - `subagents: list[str]` replaces single `subagent` field
3. **No backward compatibility** - Clean migration, no validation for conflicting fields
4. **Option A: Multiple task tool calls** - Leverages deepagents infrastructure with executor coordination
5. **Wave-based search** - Progressive depth (list → glob → grep) for efficiency
6. **LLM-driven strategy** - Intelligent directory/pattern selection based on target
7. **Match validation** - Ensures relevance through LLM ranking, not just filename matching
8. **Parallel via LLM tool calling** - Modern LLMs call multiple tools in single response
9. **Automatic thread isolation** - deepagents task tool creates branches per subagent
10. **Wave cap applies** - Parallel spawns counted toward existing subagent cap

---

## Next Steps

1. **User review** - Review this design draft for approval
2. **RFC formalization** - Generate RFC-XXX documenting this design (Platonic Coding Phase 1)
3. **Implementation** - Follow phased implementation plan
4. **Verification** - Run `./scripts/verify_finally.sh` after implementation

---

*Design complete. Ready for RFC formalization upon approval.*