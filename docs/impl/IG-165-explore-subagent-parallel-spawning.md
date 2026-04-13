# IG-165: Explore Subagent and Parallel Spawning Implementation

**Implementation Guide**: 165
**RFC**: RFC-605
**Title**: Explore Subagent and Parallel Spawning
**Status**: Draft
**Created**: 2026-04-13
**Dependencies**: RFC-605, RFC-201, RFC-100, RFC-600

## Overview

This guide implements RFC-605's two major capabilities:
1. **Explore Subagent**: Targeted filesystem search agent with wave-based strategy
2. **Parallel Subagent Spawning**: Multi-subagent execution via StepAction.subagents list

**Breaking Change**: Schema migration with NO backward compatibility.

## Requirements Analysis

### Core Requirements (MUST)

#### Explore Subagent

1. **Wave-based search strategy**:
   - MUST implement 3-wave progression: list → glob → grep
   - MUST use LLM for strategy generation (SearchStrategy schema)
   - MUST validate matches with LLM ranking (high/medium/low relevance)
   - MUST limit candidates to 20 for validation efficiency

2. **LangGraph engine**:
   - MUST implement nodes: analyze_target, execute_wave, validate_matches, synthesize_results
   - MUST use conditional edge: should_continue_search
   - MUST emit events: ExploreStrategyEvent, ExploreWaveEvent, ExploreMatchEvent, ExploreCompletedEvent

3. **Tool reuse**:
   - MUST use existing langchain tools: list_files, glob, grep, read_file
   - MUST NOT implement custom file operation tools

4. **State schema**:
   - MUST define ExploreState with search_target, workspace, strategy, waves, candidates, matches
   - MUST inherit workspace ContextVar from parent thread

#### Parallel Spawning

5. **Schema migration**:
   - MUST remove `subagent: str | None` from StepAction
   - MUST add `subagents: list[str] | None` to StepAction
   - MUST NOT provide backward compatibility (breaking change)

6. **Executor routing**:
   - MUST detect step.subagents length: 1 → single, N → parallel
   - MUST implement `_execute_parallel_subagents_via_task()` method
   - MUST aggregate outcomes into combined StepResult

7. **Parallel execution mechanics**:
   - MUST build combined prompt for CoreAgent: "Execute in parallel:..."
   - MUST rely on LLM parallel tool calling (N task tool calls)
   - MUST count parallel spawns toward wave cap (N subagents = N toward cap)
   - MUST NOT manually generate thread IDs (automatic via deepagents)

8. **Integration**:
   - MUST register explore factory in SUBAGENT_FACTORIES
   - MUST update LLMPlanner prompt with subagent selection guide
   - MUST update configuration schema with explore settings

### Constraints

1. **Thread isolation**: Automatic via deepagents task tool - no manual thread ID generation
2. **Wave cap enforcement**: Existing cap logic applies to parallel spawns
3. **Workspace boundary**: Explore inherits workspace from parent, respects search boundary
4. **Match limiting**: Max 20 candidates for validation, max 5 matches returned
5. **Wave progression**: Stop if wave > max_waves OR candidates >= 20
6. **Relevance threshold**: Return matches with high/medium relevance only

### Invariants

1. **Explore always uses tools**: Never implements custom file operations
2. **Parallel spawns count toward cap**: Cannot exceed max_subagent_tasks_per_wave
3. **Single outcome per parallel step**: Executor aggregates N results into one StepResult
4. **No backward compat**: All StepAction usages must use subagents list
5. **Thread safety**: Automatic via langgraph's atomic state updates

## Module Structure

### New Modules

```
src/soothe/subagents/explore/
├── __init__.py                # Exports: create_explore_subagent
├── implementation.py          # Factory function
├── engine.py                  # LangGraph engine builder
├── schemas.py                 # ExploreState, SearchStrategy, ValidationResult
├── events.py                  # ExploreStrategyEvent, ExploreWaveEvent, ExploreMatchEvent, ExploreCompletedEvent
└── nodes/
    ├── __init__.py
    ├── analyze_target.py      # analyze_target_node
    ├── execute_wave.py        # execute_wave_node
    ├── validate_matches.py    # validate_matches_node
    └── synthesize_results.py  # synthesize_results_node
```

### Modified Modules

```
src/soothe/cognition/agent_loop/
├── schemas.py                 # StepAction.subagents field (breaking change)
├── executor.py                # _execute_parallel_subagents_via_task() method
├── planner.py                 # Prompt enhancement with explore guide

src/soothe/core/resolver/
└── _resolver_tools.py         # SUBAGENT_FACTORIES["explore"] registration

src/soothe/config/
├── models.py                  # ExploreSubagentConfig class
├── config.yml                 # Explore configuration section

tests/unit/
├── test_stepaction_schema.py  # Schema validation tests
├── test_explore_engine.py     # Explore unit tests
├── test_executor_parallel.py  # Parallel spawning tests
```

## Type Definitions

### Explore Schemas

```python
# src/soothe/subagents/explore/schemas.py

from typing import TypedDict, Annotated
from operator import add
from langgraph.graph.message import add_messages

class ExploreState(TypedDict):
    messages: Annotated[list, add_messages]
    search_target: str
    workspace: str
    search_strategy: dict
    search_waves: list[dict]
    candidates: list[str]
    validated_matches: list[dict]
    current_wave: int
    max_waves: int

class SearchStrategy(BaseModel):
    priority_dirs: list[str] = Field(min_items=3, max_items=5)
    file_patterns: list[str]
    content_keywords: list[str]
    search_type: str  # "code", "config", "docs", "general"

class ValidationResult(BaseModel):
    matches: list[dict]  # [{path, relevance, reason, description}]
```

### StepAction Schema (Modified)

```python
# src/soothe/cognition/agent_loop/schemas.py

class StepAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tools: list[str] | None = None
    subagents: list[str] | None = None  # NEW (replaces subagent field)
    expected_output: str
    dependencies: list[str] | None = None
```

### Explore Config

```python
# src/soothe/config/models.py

class ExploreSubagentConfig(BaseModel):
    enabled: bool = True
    model_role: str = "default"
    max_waves: int = 3
    validation_threshold: str = "medium"
    max_candidates_per_wave: int = 20
```

## Interface Signatures

### Explore Factory

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
        context: workspace (work_dir), max_waves settings

    Returns:
        CompiledSubAgent dict with name, description, runnable
    """
```

### Explore Engine

```python
def build_explore_engine(
    model: BaseChatModel,
    config: ExploreConfig,
) -> CompiledStateGraph:
    """Build explore subagent runnable.

    Returns:
        LangGraph compiled state graph with 4 nodes + conditional edges
    """
```

### Parallel Spawning Executor

```python
async def _execute_parallel_subagents_via_task(
    self,
    step: StepAction,
    thread_id: str,
    workspace: str | None,
) -> tuple[list[StreamEvent], StepResult]:
    """Execute multiple subagents via parallel task tool calls.

    Args:
        step: StepAction with subagents list (length > 1)
        thread_id: Parent thread ID
        workspace: Workspace path

    Returns:
        Tuple of (stream events, aggregated StepResult)
    """
```

### Node Functions

```python
async def analyze_target_node(state: ExploreState) -> dict
async def execute_wave_node(state: ExploreState) -> dict
async def validate_matches_node(state: ExploreState) -> dict
async def synthesize_results_node(state: ExploreState) -> dict

def should_continue_search(state: ExploreState) -> str
```

## Implementation Strategy

### Phase 1: Explore Subagent Core (6 files)

**Order**: Schemas → Events → Engine skeleton → Nodes → Factory

1. `schemas.py` - Define ExploreState, SearchStrategy, ValidationResult
2. `events.py` - Register 4 explore events with event_catalog
3. `engine.py` - Build LangGraph skeleton (nodes + edges, no node logic)
4. `nodes/analyze_target.py` - LLM strategy generation
5. `nodes/execute_wave.py` - Wave execution with tools
6. `nodes/validate_matches.py` - Match validation and ranking
7. `nodes/synthesize_results.py` - Final output formatting
8. `implementation.py` - Factory function

### Phase 2: Schema Migration (Breaking Change)

**Critical**: All existing StepAction usages must update

1. Update `schemas.py` - Remove `subagent`, add `subagents`
2. Update all existing code using StepAction:
   - `executor.py` - Check for step.subagent references
   - `planner.py` - Plan generation outputs
   - Tests - All StepAction instantiations
3. Run grep to find all `step.subagent` references: replace with `step.subagents`

### Phase 3: Executor Parallel Spawning

1. Add `_execute_step_collecting_events` routing logic
2. Implement `_execute_parallel_subagents_via_task` method
3. Update outcome aggregation in `_stream_and_collect` (budget tracking)
4. Ensure wave cap counting works for parallel spawns

### Phase 4: Integration

1. Register explore in `SUBAGENT_FACTORIES`
2. Update LLMPlanner `_build_plan_prompt` with subagent selection guide
3. Add ExploreSubagentConfig to config models
4. Update `config.yml` with explore settings

### Phase 5: Tests

1. Unit tests for explore nodes (mock LLM responses)
2. Unit tests for schema (single vs multiple subagents)
3. Unit tests for executor (parallel spawning mechanics)
4. Integration tests for explore end-to-end
5. Integration tests for parallel execution (2-3 explores)
6. Integration tests for AgentLoop auto-selection

## Error Handling

### Explore Subagent

1. **Strategy generation failure**: Fallback to default strategy (generic search)
2. **Tool execution failure**: Continue to next wave, log error
3. **Validation failure**: Return top candidates without ranking (best effort)
4. **Empty candidates**: Return "No matches found" message
5. **LLM timeout**: Use timeout from config (120s per validation)

### Executor Parallel Spawning

1. **LLM fails to output N task calls**: Log warning, continue with available calls
2. **Subagent timeout**: Count toward completions, mark as failed in aggregated outcome
3. **Cap exceeded during parallel execution**: Stop stream immediately, return partial results
4. **One subagent fails**: Aggregate remaining successful outputs, mark step success=True with mixed outcomes

## Testing Strategy

### Unit Tests

**Explore Engine**:
- `test_analyze_target_node` - Mock LLM, verify strategy generation
- `test_execute_wave_node_wave1` - Mock list_files tool, verify candidates
- `test_execute_wave_node_wave2` - Mock glob tool, verify patterns
- `test_execute_wave_node_wave3` - Mock grep tool, verify keywords
- `test_should_continue_search` - Verify conditional logic (wave depth, candidate count)
- `test_validate_matches_node` - Mock LLM, verify ranking
- `test_synthesize_results_node` - Verify output formatting

**Schema Migration**:
- `test_stepaction_single_subagent` - subagents=["explore"] validates
- `test_stepaction_multiple_subagents` - subagents=["explore", "research"] validates
- `test_stepaction_none` - subagents=None validates

**Executor**:
- `test_execute_single_subagent_routing` - Length=1 routes correctly
- `test_execute_parallel_subagents_routing` - Length>1 routes correctly
- `test_parallel_outcome_aggregation` - Verify combined outcome dict
- `test_wave_cap_counting` - Parallel spawns count toward cap

### Integration Tests

**Explore End-to-End**:
- `test_explore_find_auth_module` - Real filesystem, real LLM (or mock responses)
- `test_explore_wave_progression` - Verify wave 1→2→3 execution
- `test_explore_match_quality` - Verify high/medium relevance filtering

**Parallel Execution**:
- `test_parallel_two_explores` - Two explore subagents concurrently
- `test_parallel_mixed_explore_research` - Mixed subagent types
- `test_parallel_thread_isolation` - Verify thread branches created

**AgentLoop Integration**:
- `test_agentloop_explore_auto_selection` - LLM chooses explore for "find X"
- `test_agentloop_parallel_execution` - Plan output with subagents list
- `test_metrics_aggregation` - Verify parallel outcomes aggregated

## Verification Commands

After implementation:

```bash
# Unit tests
pytest tests/unit/test_explore_engine.py
pytest tests/unit/test_stepaction_schema.py
pytest tests/unit/test_executor_parallel.py

# Integration tests
pytest tests/integration/test_explore_subagent.py
pytest tests/integration/test_parallel_spawning.py

# Full verification
./scripts/verify_finally.sh
```

## Code Standards

- Type hints on all public functions
- Google-style docstrings with Args, Returns, Raises
- Ruff formatting (zero errors)
- No bare except (typed exception handling)
- Follow existing patterns in subagents/browser/, subagents/research/
- Use langchain tools (list_files, glob, grep, read_file) - no custom implementations

## Migration Checklist

### Breaking Changes (No Backward Compatibility)

All existing code using `step.subagent` must update:

```bash
# Find all references
grep -r "step\.subagent" src/ tests/
grep -r "\.subagent = " src/ tests/
grep -r "subagent: str" src/ tests/

# Replace pattern
step.subagent = "browser" → step.subagents = ["browser"]
if step.subagent: → if step.subagents:
```

### New Imports

```python
# Resolver
from soothe.subagents.explore.implementation import create_explore_subagent

# Executor
from soothe.subagents.explore.events import ExploreStrategyEvent

# Config
from soothe.config.models import ExploreSubagentConfig
```

## Key Design Decisions

1. **No backward compatibility** - Clean schema migration
2. **Nodes as separate functions** - Easier testing and debugging
3. **Wave progression in execute_wave_node** - Single node handles all waves
4. **Match limiting to 20** - Efficiency for LLM validation
5. **Executor aggregates outcomes** - Single StepResult for parallel wave
6. **LLM parallel tool calling** - Leverage modern LLM capabilities
7. **Automatic thread isolation** - Trust deepagents infrastructure
8. **Configurable max_waves** - Default 3, user can adjust

## Open Questions

1. **Explore subagent model**: Use cheaper model (gpt-4o-mini) for strategy/validation? (Decision: Use same model role as other subagents by default)
2. **Parallel aggregate mode**: Concatenate vs summarize vs best output? (Decision: Default "concatenate", configurable)
3. **Match description length**: How detailed should match descriptions be? (Decision: Brief one-line descriptions, ~50 chars)

---

**Implementation Guide Complete**. Proceed to coding plan upon approval.