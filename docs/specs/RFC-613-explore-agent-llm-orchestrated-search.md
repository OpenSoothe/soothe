# RFC-613: Explore Agent — LLM-Orchestrated Iterative Search

**RFC**: 613
**Title**: Explore Agent — LLM-Orchestrated Iterative Search
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-24
**Updated**: 2026-04-24
**Authors**: Platonic Coding Workflow
**Depends on**: RFC-000, RFC-001, RFC-100, RFC-600
**Supersedes**: RFC-605 (explore subagent portion only)
**Related**: RFC-601, RFC-200, RFC-211

## Abstract

This RFC defines the architecture of Soothe's **Explore agent**: a specialized subagent for targeted filesystem search using LLM-orchestrated iterative tool selection. Unlike the previous RFC-605 design which used a fixed wave-based progression (list → glob → grep), this agent dynamically decides which read-only filesystem tool to call next based on accumulated findings, producing better results with fewer unnecessary operations.

Key features:
- **LLM-orchestrated iteration**: The agent plans, executes, and assesses at each step, adapting its strategy dynamically
- **Configurable thoroughness**: Three levels (quick, medium, thorough) control iteration caps and content reading
- **Read-only tools only**: Uses deepagents' existing `glob`, `grep`, `ls`, `read_file` and Soothe's `file_info`
- **Plugin-compliant**: Follows RFC-600 `@plugin` and `@subagent` decorator patterns

> **Note**: The parallel subagent spawning portion of RFC-605 will be addressed in a separate future RFC.

---

## 1. Problem Statement

RFC-605 defined an Explore subagent with a **fixed wave-based search progression** (list → glob → grep). This approach has fundamental limitations:

1. **Rigid strategy**: Cannot adapt when early results reveal a better approach (e.g., wave 1 finds the target — waves 2 and 3 are wasted)
2. **No content validation during search**: Match validation only happens after all waves complete
3. **No concept of search depth**: All searches run the same number of waves regardless of target complexity
4. **Inefficient for simple targets**: A simple "find auth.py" requires running all 3 waves before validation

Claude Code's explore agent demonstrates that an **LLM-orchestrated iterative approach** is more effective: the agent decides what tool to call next based on what it has found so far, adapting strategy dynamically.

---

## 2. Design Goals

1. **Intelligent tool selection** — LLM decides which read-only filesystem tool to use at each step
2. **Adaptive strategy** — Agent adjusts approach based on accumulated findings
3. **Configurable thoroughness** — Three levels control iteration caps and content reading
4. **Efficient resource usage** — Stop early when target is found, avoid unnecessary tool calls
5. **Read-only safety** — Explore never modifies the filesystem
6. **Plugin-compliant** — Follows existing `@plugin`/`@subagent` patterns (RFC-600)
7. **Tool reuse** — Uses deepagents' existing filesystem tools, no custom implementations

---

## 3. Guiding Principles

1. **LLM as Orchestrator** — The LLM plans each step, evaluates results, and decides whether to continue
2. **Thoroughness as Iteration Cap** — Simple, predictable resource control through max iterations
3. **Read-Only Boundary** — Explore is a search agent; file modification is out of scope
4. **Tool Reuse** — Leverage deepagents' `glob`, `grep`, `ls`, `read_file`; no custom file tools
5. **Follow Existing Patterns** — Same plugin/factory/event structure as research and browser subagents

---

## 4. Architecture

### 4.1 Engine Flow

```
┌──────────────────────────────────────────────────────────┐
│  Explore Engine (LangGraph StateGraph)                    │
│                                                           │
│  START → plan_search (LLM)                               │
│           ↓ Generate initial search action                │
│          execute_action (tool call)                       │
│           ↓ Glob / Grep / ls / read_file                  │
│          assess_results (LLM)                             │
│           ↓ Continue? Adjust? Finish?                     │
│           ├─ continue → execute_action                    │
│           ├─ adjust → plan_search (refined strategy)      │
│           └─ finish → synthesize → END                    │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Thoroughness Levels

The calling agent or user specifies thoroughness, which controls iteration caps and content reading:

| Level | Max Iterations | Read Content? | When to Use |
|-------|---------------|---------------|-------------|
| quick | 2 | No | Simple filename search, known paths |
| medium | 4 | Targeted reads | Finding a module, specific pattern |
| thorough | 6 | Deep reads | Conceptual search, unknown structure |

When thoroughness is not specified, the agent infers it from the target: literal filenames → quick, module/concept descriptions → medium, "understand how X works" → thorough.

### 4.3 Available Tools

The Explore agent has access to a restricted subset of read-only filesystem tools:

| Tool | Source | Purpose |
|------|--------|---------|
| `glob` | deepagents FilesystemMiddleware | Find files matching patterns |
| `grep` | deepagents FilesystemMiddleware | Search file contents |
| `ls` | deepagents FilesystemMiddleware | List directory contents |
| `read_file` | deepagents FilesystemMiddleware | Read file snippets (capped at ~50 lines) |
| `file_info` | SootheFilesystemMiddleware | Get file metadata |

**No write tools** — Explore never modifies the filesystem.

---

## 5. Specification

### 5.1 State Schema

```python
class ExploreState(TypedDict):
    messages: Annotated[list, add_messages]
    search_target: str           # What we're looking for
    workspace: str               # Search boundary
    thoroughness: str            # "quick" | "medium" | "thorough"
    findings: list[dict]         # Accumulated [{path, snippet, relevance}]
    iterations_used: int         # Current iteration count
    max_iterations: int          # Cap from thoroughness level
    assessment_decision: str     # "continue" | "adjust" | "finish"
```

### 5.2 Output Schema

```python
class MatchEntry(BaseModel):
    path: str
    relevance: str               # "high" | "medium" | "low"
    description: str             # One-line description (~50 chars)
    snippet: str | None          # Relevant content (if read during search)

class ExploreResult(BaseModel):
    target: str
    thoroughness: str
    matches: list[MatchEntry]    # Top 3-5 matches, sorted by relevance
    summary: str                 # Brief answer to the search target
```

### 5.3 Engine Nodes

#### plan_search

- **Input**: `search_target`, `workspace`, accumulated `findings` (if any)
- **Process**: LLM generates the next search action — which tool, what query, what directory/pattern
- **Output**: Tool call(s) appended to `messages`
- **Behavior on first call**: Analyzes target intent, generates initial search strategy
- **Behavior on subsequent calls (adjust)**: Refines strategy based on findings so far
- **Fallback**: On LLM failure, defaults to `glob` for filename patterns derived from the target

#### execute_action

- **Input**: Pending tool calls from `plan_search`
- **Process**: Executes tool calls against the filesystem backend
- **Output**: Tool results appended to `messages`, `findings` updated with discovered paths, `iterations_used` incremented
- **Error handling**: Log tool execution errors, continue to next iteration

#### assess_results

- **Input**: `search_target`, `findings`, `iterations_used`, `max_iterations`
- **Process**: LLM evaluates whether findings sufficiently answer the target
- **Output**: `assessment_decision` — `"continue"` (more of same), `"adjust"` (new strategy), or `"finish"` (sufficient results)
- **Forced finish**: If `iterations_used >= max_iterations`, decision is overridden to `"finish"`

#### synthesize

- **Input**: All `findings`, `search_target`
- **Process**: Format top 3-5 matches with descriptions and optional snippets
- **Output**: Final `ExploreResult` as `AIMessage`
- **Emits**: `soothe.capability.explore.completed` event

### 5.4 Conditional Edge Logic

```python
def route_after_assessment(state: ExploreState) -> str:
    """Route based on LLM assessment and iteration budget."""

    if state["iterations_used"] >= state["max_iterations"]:
        return "synthesize"

    decision = state["assessment_decision"]

    if decision == "finish":
        return "synthesize"
    elif decision == "adjust":
        return "plan_search"
    else:  # "continue"
        return "execute_action"
```

### 5.5 Events

| Event Type | When | Verbosity Tier |
|-----------|------|---------------|
| `soothe.capability.explore.started` | Search begins | NORMAL |
| `soothe.capability.explore.executing` | Tool executing | DETAILED |
| `soothe.capability.explore.assessing` | Assessment in progress | DETAILED |
| `soothe.capability.explore.completed` | Search complete | NORMAL |

```python
from typing import Literal
from pydantic import ConfigDict
from soothe.core.base_events import SubagentEvent
from soothe.core.event_catalog import register_event, VerbosityTier

class ExploreStartedEvent(SubagentEvent):
    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.started"] = "soothe.capability.explore.started"
    search_target: str
    thoroughness: str

class ExploreExecutingEvent(SubagentEvent):
    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.executing"] = "soothe.capability.explore.executing"
    tool_name: str
    tool_args: dict
    results_count: int

class ExploreAssessingEvent(SubagentEvent):
    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.assessing"] = "soothe.capability.explore.assessing"
    decision: str  # "continue" | "adjust" | "finish"
    findings_count: int
    iterations_used: int

class ExploreCompletedEvent(SubagentEvent):
    model_config = ConfigDict(extra="allow")
    type: Literal["soothe.capability.explore.completed"] = "soothe.capability.explore.completed"
    total_findings: int
    top_matches: list[dict]
    thoroughness: str
    iterations_used: int
    duration_ms: int

# Event registration
register_event(
    ExploreStartedEvent,
    summary_template="Explore started: {search_target} ({thoroughness})",
    tier=VerbosityTier.NORMAL,
)
register_event(
    ExploreExecutingEvent,
    summary_template="Explore executing: {tool_name} ({results_count} results)",
    tier=VerbosityTier.DETAILED,
)
register_event(
    ExploreAssessingEvent,
    summary_template="Explore assessed: {decision} ({findings_count} findings, iter {iterations_used})",
    tier=VerbosityTier.DETAILED,
)
register_event(
    ExploreCompletedEvent,
    summary_template="Explore completed: {total_findings} findings ({thoroughness}, {iterations_used} iters, {duration_ms}ms)",
    tier=VerbosityTier.NORMAL,
)
```

### 5.6 Prompt Templates

#### plan_search prompt

```
You are a filesystem search agent. Your goal is to find information about: {search_target}

Search boundary: {workspace}
Thoroughness: {thoroughness} (max {max_iterations} iterations)

Available tools:
- glob(pattern): Find files matching a glob pattern
- grep(pattern, path): Search file contents for a pattern
- ls(path): List directory contents
- read_file(path, offset, limit): Read file content (max 50 lines per read)
- file_info(path): Get file metadata

Strategy guidelines:
- Start broad (glob/ls) then narrow (grep/read_file)
- For "find X" targets: glob for filename patterns first
- For "how does X work" targets: grep for key terms, then read relevant files
- For "where is X defined" targets: grep for definitions

{findings_so_far}

Decide your next search action. Output a tool call.
```

#### assess_results prompt

```
Search target: {search_target}
Findings so far: {findings_summary}
Iterations used: {iterations_used}/{max_iterations}

Evaluate whether the findings sufficiently answer the search target.
Respond with one of:
- "continue": More searches with current strategy would help
- "adjust": Current strategy isn't working, try a different approach
- "finish": Findings are sufficient to answer the target

Decision:
```

---

## 6. Configuration

```yaml
subagents:
  explore:
    enabled: true
    model: "default"
    config:
      thoroughness: "medium"
      max_iterations:
        quick: 2
        medium: 4
        thorough: 6
      max_read_lines: 50
      max_matches_returned: 5
```

```python
class ExploreSubagentConfig(BaseModel):
    """Explore-specific configuration, stored inside SubagentConfig.config."""

    thoroughness: str = "medium"
    max_iterations: dict[str, int] = {
        "quick": 2,
        "medium": 4,
        "thorough": 6,
    }
    max_read_lines: int = 50
    max_matches_returned: int = 5
```

---

## 7. Plugin Definition

```python
@plugin(name="explore", version="1.0.0", trust_level="built-in", description="Targeted filesystem search agent")
class ExplorePlugin:
    @subagent(
        name="explore",
        description=(
            "Targeted filesystem search agent. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness. Best for 'find', 'locate', "
            "'search for' goals."
        ),
        triggers=["find", "locate", "search for", "where is", "look for"],
    )
    async def create_subagent(
        self,
        model: BaseChatModel,
        config: SootheConfig,
        context: dict[str, Any],
    ) -> CompiledSubAgent:
        return create_explore_subagent(model, config, context)
```

### Factory Function

```python
def create_explore_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledSubAgent:
    """Create explore subagent.

    Args:
        model: LLM for search planning and result assessment.
        config: Soothe configuration.
        context: workspace (work_dir), thoroughness settings.

    Returns:
        CompiledSubAgent dict with name, description, runnable.
    """
    subagent_config = config.subagents.get("explore", SubagentConfig())
    explore_config = ExploreSubagentConfig(**subagent_config.config)
    workspace = context.get("work_dir", "")
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

---

## 8. File Structure

```
src/soothe/subagents/explore/
├── __init__.py           # Plugin + exports
├── implementation.py     # Factory function: create_explore_subagent()
├── engine.py             # LangGraph engine builder: build_explore_engine()
├── schemas.py            # ExploreState, MatchEntry, ExploreResult, ExploreSubagentConfig
├── events.py             # 4 explore events with register_event()
└── prompts.py            # LLM prompt templates for plan/assess/synthesize
```

---

## 9. Integration

### 9.1 Subagent Registry

```python
# In core/resolver/_resolver_tools.py, add to _get_subagent_factories()
def _get_subagent_factories() -> dict[str, Callable]:
    from soothe.subagents.explore.implementation import create_explore_subagent
    # ... existing factories ...
    factories["explore"] = create_explore_subagent
    return factories
```

### 9.2 AgentLoop LLMPlanner Prompt

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

### 9.3 PolicyProtocol Usage

| Agent | Action | Check |
|-------|--------|-------|
| Explore | `explore_search` | Filesystem read permission within workspace |

---

## 10. Relationship to Other RFCs

| RFC | Relationship |
|-----|-------------|
| RFC-605 | **Superseded** (explore portion). Parallel spawning portion remains for future RFC |
| RFC-601 | Peer subagent — follows same plugin/factory/event patterns as research |
| RFC-600 | Plugin extension system — `@plugin` and `@subagent` decorators |
| RFC-100 | CoreAgent runtime — `CompiledSubAgent` interface |
| RFC-200 | AgentLoop — `StepAction.subagent` integration |
| RFC-211 | Tool result optimization — read snippet efficiency |
| RFC-101 | Tool interface — reuse of existing filesystem tools |

---

## 11. Error Handling

| Scenario | Behavior |
|----------|----------|
| LLM plan failure | Fallback to default search (`glob` for filename patterns derived from target) |
| Tool execution failure | Log error, continue to next iteration |
| No results found | Return empty matches with summary "No matches found for target" |
| Iteration budget exceeded | Force synthesize with whatever findings exist |
| Read file too large | Cap at `max_read_lines` (default 50), note truncation in findings |
| Invalid thoroughness | Default to "medium" |

---

## 12. Testing Requirements

### Unit Tests

- `test_plan_search_node` — Mock LLM, verify tool call generation
- `test_execute_action_node` — Mock tools, verify findings update
- `test_assess_results_node` — Mock LLM, verify continue/adjust/finish decisions
- `test_route_after_assessment` — Verify conditional edge logic
- `test_synthesize_node` — Verify output formatting
- `test_thoroughness_caps` — Verify iteration limits per level
- `test_explore_config` — Verify configuration parsing
- `test_fallback_on_llm_failure` — Verify default glob fallback

### Integration Tests

- `test_explore_find_by_name` — Real filesystem, "find auth module"
- `test_explore_find_by_concept` — "how does authentication work"
- `test_explore_quick_thoroughness` — Verify quick search stops early
- `test_explore_thorough_thoroughness` — Verify thorough search reads content
- `test_explore_no_results` — Verify graceful empty results

---

## 13. Migration from RFC-605

RFC-605 contained two concerns: the Explore subagent and parallel subagent spawning. This RFC supersedes **only the Explore portion**. Changes from RFC-605:

| Aspect | RFC-605 (old) | This RFC (new) |
|--------|--------------|----------------|
| Search strategy | Fixed waves (list→glob→grep) | LLM-orchestrated iterative |
| LLM usage | Strategy generation + post-search validation | Planning + assessment at each step |
| Thoroughness | `max_waves` (default 3) | 3 levels with iteration caps |
| Parallel spawning | Included | Separate future RFC |
| StepAction migration | Included (subagent→subagents) | Separate future RFC |
| Events | Wave-focused (strategy, wave, match, completed) | Iteration-focused (started, executing, assessing, completed) |
| File structure | 6 files + `nodes/` subpackage | 6 files (no subpackage) |
| Search strategy schema | `SearchStrategy(priority_dirs, file_patterns, content_keywords)` | No fixed schema — LLM generates tool calls directly |

---

## 14. Open Questions

1. **Merge assess_results into plan_search?** Currently separate for clarity, but merging would reduce LLM calls. Trade-off: clarity vs. efficiency.
2. **Quick thoroughness skip assess_results?** Would save an LLM call for simple searches at the cost of less precise early termination.

---

## 15. Implementation Status

- ⚠️ Explore engine (pending)
- ⚠️ Explore factory function (pending)
- ⚠️ Explore events (pending)
- ⚠️ Explore configuration (pending)
- ⚠️ Subagent registry update (pending)
- ⚠️ LLMPlanner prompt update (pending)
- ⚠️ Unit tests (pending)
- ⚠️ Integration tests (pending)

---

*Explore agent: LLM-orchestrated iterative filesystem search with configurable thoroughness levels and read-only tools.*
