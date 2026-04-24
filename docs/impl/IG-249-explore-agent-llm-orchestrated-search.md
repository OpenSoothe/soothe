# IG-249: Explore Agent — LLM-Orchestrated Iterative Search

**RFC**: RFC-613
**Created**: 2026-04-24
**Status**: Draft
**Dependencies**: RFC-613, RFC-600, RFC-601

---

## Overview

Implement RFC-613's Explore agent: a specialized subagent for targeted filesystem search using LLM-orchestrated iterative tool selection. Unlike the previous RFC-605 design (fixed wave-based progression), this agent dynamically decides which read-only filesystem tool to call next based on accumulated findings.

**Key deliverables**:
- Explore engine (LangGraph StateGraph with 4 nodes + conditional edges)
- Explore schemas (ExploreState, MatchEntry, ExploreResult, ExploreSubagentConfig)
- Explore events (4 events with register_event())
- Explore prompts (plan/assess/synthesize templates)
- Plugin registration + factory function
- Subagent registry update + LLMPlanner prompt update
- Configuration schema
- Unit tests + integration tests

---

## Phase 1: Schemas + Events + Prompts (3 files)

### 1.1 Create `schemas.py`

**File**: `packages/soothe/src/soothe/subagents/explore/schemas.py`

```python
"""Explore subagent schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ExploreState(TypedDict):
    """State schema for explore engine graph."""

    messages: Annotated[list, add_messages]
    search_target: str
    workspace: str
    thoroughness: Literal["quick", "medium", "thorough"]
    findings: list[dict]         # [{path, snippet, relevance}]
    iterations_used: int
    max_iterations: int
    assessment_decision: Literal["continue", "adjust", "finish"]


class MatchEntry(BaseModel):
    """A single match result from the explore agent."""

    path: str
    relevance: Literal["high", "medium", "low"]
    description: str             # One-line description (~50 chars)
    snippet: str | None = None   # Relevant content (if read during search)


class ExploreResult(BaseModel):
    """Final output of the explore agent."""

    target: str
    thoroughness: str
    matches: list[MatchEntry]    # Top matches, sorted by relevance
    summary: str                 # Brief answer to the search target


class ExploreSubagentConfig(BaseModel):
    """Explore-specific configuration, stored inside SubagentConfig.config."""

    thoroughness: str = "medium"
    max_iterations: dict[str, int] = Field(default_factory=lambda: {
        "quick": 2,
        "medium": 4,
        "thorough": 6,
    })
    max_read_lines: int = 50
    max_matches_returned: int = 5
```

### 1.2 Create `events.py`

**File**: `packages/soothe/src/soothe/subagents/explore/events.py`

Follow the research events pattern exactly:
- Inherit from `SootheEvent` (research uses `SootheEvent` directly, not `SubagentEvent`)
- Use `Literal[...]` for `type` field
- Add `model_config = ConfigDict(extra="allow")`
- Register events with `register_event()` and `VerbosityTier`
- Export event type constants

Event types:
| Class | Type String | Tier |
|-------|-----------|------|
| `ExploreStartedEvent` | `soothe.capability.explore.started` | NORMAL |
| `ExploreExecutingEvent` | `soothe.capability.explore.executing` | DETAILED |
| `ExploreAssessingEvent` | `soothe.capability.explore.assessing` | DETAILED |
| `ExploreCompletedEvent` | `soothe.capability.explore.completed` | NORMAL |

### 1.3 Create `prompts.py`

**File**: `packages/soothe/src/soothe/subagents/explore/prompts.py`

```python
"""Explore subagent prompt templates."""

PLAN_SEARCH = """\
You are a filesystem search agent. Your goal is to find information about: {search_target}

Search boundary: {workspace}
Thoroughness: {thoroughness} (max {max_iterations} iterations)

Available tools:
- glob(pattern): Find files matching a glob pattern
- grep(pattern, path): Search file contents for a pattern
- ls(path): List directory contents
- read_file(path, offset, limit): Read file content (max {max_read_lines} lines per read)
- file_info(path): Get file metadata

Strategy guidelines:
- Start broad (glob/ls) then narrow (grep/read_file)
- For "find X" targets: glob for filename patterns first
- For "how does X work" targets: grep for key terms, then read relevant files
- For "where is X defined" targets: grep for definitions

{findings_so_far}

Decide your next search action. Output a tool call."""

ASSESS_RESULTS = """\
Search target: {search_target}
Findings so far: {findings_summary}
Iterations used: {iterations_used}/{max_iterations}

Evaluate whether the findings sufficiently answer the search target.
Respond with one of:
- "continue": More searches with current strategy would help
- "adjust": Current strategy isn't working, try a different approach
- "finish": Findings are sufficient to answer the target

Decision:"""

SYNTHESIZE = """\
Based on the search findings below, provide a concise summary answering: {search_target}

Findings:
{findings_detail}

Return a JSON object with:
- "matches": top {max_matches} matches, each with "path", "relevance" (high/medium/low), "description", "snippet" (null if not read)
- "summary": brief answer to the search target"""
```

---

## Phase 2: Engine (1 file)

### 2.1 Create `engine.py`

**File**: `packages/soothe/src/soothe/subagents/explore/engine.py`

Build a LangGraph `StateGraph` following the research engine pattern:
- State class: `ExploreState` (from schemas)
- Nodes: `plan_search`, `execute_action`, `assess_results`, `synthesize`
- Edges: `START → plan_search → execute_action → assess_results → (conditional) → ... → synthesize → END`
- Conditional edge: `route_after_assessment()` returning "plan_search" | "execute_action" | "synthesize"

**Node implementation details**:

#### `plan_search` node
- Build prompt from `PLAN_SEARCH` template
- Call `model.ainvoke()` with the prompt
- The LLM should produce tool calls (glob/grep/ls/read_file/file_info)
- Append `AIMessage` with tool_calls to state messages
- On first call: emit `ExploreStartedEvent`
- On subsequent calls (adjust path): emit `ExploreAssessingEvent(decision="adjust")`

#### `execute_action` node
- Extract tool calls from the last `AIMessage`
- Execute each tool call via the filesystem backend
- Append `ToolMessage` results to state messages
- Update `findings` with discovered paths
- Increment `iterations_used`
- Emit `ExploreExecutingEvent(tool_name=..., results_count=...)`

#### `assess_results` node
- Build prompt from `ASSESS_RESULTS` template
- Call `model.ainvoke()` with structured output → decision: "continue" | "adjust" | "finish"
- Update `assessment_decision` in state
- Emit `ExploreAssessingEvent(decision=..., findings_count=..., iterations_used=...)`
- Force `assessment_decision = "finish"` if `iterations_used >= max_iterations`

#### `synthesize` node
- Build prompt from `SYNTHESIZE` template
- Call `model.ainvoke()` with structured output → `ExploreResult`
- Emit `ExploreCompletedEvent(total_findings=..., top_matches=..., thoroughness=..., iterations_used=..., duration_ms=...)`
- Return final `AIMessage` with the `ExploreResult` as content

**How to get tools**: The explore engine receives read-only tools at build time. The builder function:

```python
def build_explore_engine(
    model: BaseChatModel,
    config: ExploreSubagentConfig,
    workspace: str,
) -> CompiledStateGraph:
```

The engine creates a `ToolNode` with the read-only tools injected via the builder. Tools are obtained from deepagents' `FilesystemMiddleware` (glob, grep, ls, read_file) and Soothe's `SootheFilesystemMiddleware` (file_info).

**Tool binding**: Use `model.bind_tools(tools)` in the `plan_search` node so the LLM can generate structured tool calls.

---

## Phase 3: Factory + Plugin (2 files)

### 3.1 Create `implementation.py`

**File**: `packages/soothe/src/soothe/subagents/explore/implementation.py`

Follow the research implementation pattern:

```python
def create_explore_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    work_dir = context.get("work_dir", "")
    subagent_config = config.subagents.get("explore", SubagentConfig())
    explore_config = ExploreSubagentConfig(**subagent_config.config)
    workspace = work_dir  # Search boundary is workspace
    runnable = build_explore_engine(model, explore_config, workspace)
    return {
        "name": "explore",
        "description": (
            "Targeted filesystem search agent. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness (quick/medium/thorough). "
            "Use when goal mentions 'find', 'locate', 'search for', or requires "
            "navigating filesystem toward a specific target."
        ),
        "runnable": runnable,
    }
```

### 3.2 Create `__init__.py`

**File**: `packages/soothe/src/soothe/subagents/explore/__init__.py`

Follow the research `__init__.py` pattern:
- Import events, event constants, and factory function
- Define `ExplorePlugin` class with `@plugin` and `@subagent` decorators
- Export all via `__all__`

Plugin definition:
```python
@plugin(
    name="explore",
    version="1.0.0",
    description="Targeted filesystem search agent",
    trust_level="built-in",
)
class ExplorePlugin:
    @subagent(
        name="explore",
        description=(
            "Targeted filesystem search agent. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness. "
            "Use for: finding modules, locating patterns, navigating codebase. "
            "DO NOT use for: simple file reads (read_file), file edits. "
            "Inputs: `target` (required), `thoroughness` (optional: 'quick', 'medium', 'thorough'). "
            "Returns matches with paths, descriptions, and optional content snippets."
        ),
        model="openai:gpt-4o-mini",
        triggers=["find", "locate", "search for", "where is", "look for"],
    )
    async def create_subagent(self, model, config, context):
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
            "thoroughness": getattr(context, "thoroughness", "medium"),
        }
        return create_explore_subagent(model, config, context_dict)
```

---

## Phase 4: Integration (3 files modified)

### 4.1 Update subagent registry

**File**: `packages/soothe/src/soothe/core/resolver/_resolver_tools.py`

Add explore to `_get_subagent_factories()`:

```python
from soothe.subagents.explore.implementation import create_explore_subagent
# In _get_subagent_factories():
factories["explore"] = create_explore_subagent
```

Also update `resolve_subagents()` to handle explore-specific kwargs (workspace from work_dir, config from SubagentConfig.config).

### 4.2 Update LLMPlanner prompt

**File**: `packages/soothe/src/soothe/cognition/agent_loop/planning_utils.py`

Add explore to the available subagents section of the plan prompt:

```xml
<AVAILABLE_SUBAGENTS>
- browser: Web automation and browsing
- research: Multi-source research and synthesis
- claude: General-purpose agent with full capabilities
- explore: Targeted filesystem search (quick/medium/thorough)

<SUBAGENT_SELECTION_GUIDE>
- "Find authentication module" → subagent="explore"
- "Locate API endpoints" → subagent="explore"
- "Search for config files" → subagent="explore"
- "How does the planner work?" → subagent="explore" (thorough)
</SUBAGENT_SELECTION_GUIDE>
</AVAILABLE_SUBAGENTS>
```

### 4.3 Update config models

**File**: `packages/soothe/src/soothe/config/models.py`

No changes needed — `ExploreSubagentConfig` lives in `schemas.py` and is accessed via `SubagentConfig.config` dict. The YAML config section goes in `config.yml`.

**File**: `packages/soothe/src/soothe/config/config.yml` (template) and `config/config.dev.yml`

Add explore subagent configuration:
```yaml
subagents:
  explore:
    enabled: true
    config:
      thoroughness: "medium"
      max_iterations:
        quick: 2
        medium: 4
        thorough: 6
      max_read_lines: 50
      max_matches_returned: 5
```

---

## Phase 5: Tests

### 5.1 Unit Tests

**File**: `packages/soothe/tests/unit/subagents/test_explore.py`

Tests:
- `test_explore_state_schema` — Verify ExploreState TypedDict fields
- `test_explore_result_schema` — Verify MatchEntry and ExploreResult validation
- `test_explore_config_defaults` — Verify ExploreSubagentConfig defaults
- `test_explore_config_invalid_thoroughness` — Verify thoroughness validation
- `test_route_after_assessment_finish` — Verify "finish" → "synthesize"
- `test_route_after_assessment_continue` — Verify "continue" → "execute_action"
- `test_route_after_assessment_adjust` — Verify "adjust" → "plan_search"
- `test_route_after_assessment_budget_exceeded` — Verify forced finish when iterations >= max
- `test_plan_search_node` — Mock LLM, verify tool call generation
- `test_execute_action_node` — Mock tools, verify findings update
- `test_assess_results_node` — Mock LLM, verify decision output
- `test_synthesize_node` — Verify output formatting
- `test_events_registered` — Verify all 4 events registered with event catalog

### 5.2 Integration Tests

**File**: `packages/soothe/tests/integration/subagents/test_explore.py`

Tests:
- `test_explore_find_by_name` — Real filesystem, "find auth module"
- `test_explore_quick_thoroughness` — Verify quick search stops at 2 iterations
- `test_explore_thorough_reads_content` — Verify thorough search reads files
- `test_explore_no_results` — Verify graceful empty results
- `test_explore_factory_returns_subagent` — Verify factory returns valid dict

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| LLM plan failure | Fallback to `glob` for filename patterns derived from target |
| Tool execution failure | Log error, continue to next iteration |
| No results found | Return empty matches with summary "No matches found for target" |
| Iteration budget exceeded | Force synthesize with whatever findings exist |
| Read file too large | Cap at `max_read_lines` (default 50), note truncation in findings |
| Invalid thoroughness | Default to "medium" |

---

## Verification

After each phase, run:

```bash
make lint           # Zero errors
pytest packages/soothe/tests/unit/subagents/test_explore.py -x
```

After all phases:

```bash
./scripts/verify_finally.sh
```

---

## Implementation Order

1. `schemas.py` — State + config + output schemas
2. `events.py` — 4 events with register_event()
3. `prompts.py` — Prompt templates
4. `engine.py` — LangGraph engine with all 4 nodes
5. `implementation.py` — Factory function
6. `__init__.py` — Plugin class + exports
7. `_resolver_tools.py` — Registry update
8. `planning_utils.py` — LLMPlanner prompt update
9. `config.yml` + `config.dev.yml` — Configuration
10. Unit tests
11. Integration tests
12. `./scripts/verify_finally.sh`
