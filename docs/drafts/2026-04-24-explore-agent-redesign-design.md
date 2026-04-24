# Explore Agent Redesign — LLM-Orchestrated Iterative Search

**Date**: 2026-04-24
**Status**: Draft
**Replaces**: RFC-605 explore subagent portion (parallel spawning to become separate RFC)
**Inspired by**: Claude Code's Explore agent pattern

---

## Problem

RFC-605 defined an Explore subagent with a fixed wave-based search progression (list → glob → grep). This approach is rigid — it cannot adapt when early results reveal a better strategy or when a simpler search would suffice. Claude Code's explore agent demonstrates that an LLM-orchestrated iterative approach is more effective: the agent decides what tool to call next based on accumulated findings, producing better results with fewer unnecessary operations.

## Design

### Approach: LLM-Orchestrated Iterative Search

The LLM acts as the search orchestrator, deciding which read-only filesystem tool to call at each step based on what it has found so far. No fixed wave order — the agent adapts its strategy dynamically.

### Architecture

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

### Thoroughness Levels

The calling agent or user specifies thoroughness, which controls iteration caps and content reading:

| Level | Max Iterations | Read Content? | When to Use |
|-------|---------------|---------------|-------------|
| quick | 2 | No | Simple filename search, known paths |
| medium | 4 | Targeted reads | Finding a module, specific pattern |
| thorough | 6 | Deep reads | Conceptual search, unknown structure |

When thoroughness is not specified, the agent infers it from the target: literal filenames → quick, module/concept descriptions → medium, "understand how X works" → thorough.

### State Schema

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

### Available Tools (read-only)

The Explore agent has access to a restricted subset of read-only filesystem tools:

| Tool | Source | Purpose |
|------|--------|---------|
| `glob` | deepagents FilesystemMiddleware | Find files matching patterns |
| `grep` | deepagents FilesystemMiddleware | Search file contents |
| `ls` | deepagents FilesystemMiddleware | List directory contents |
| `read_file` | deepagents FilesystemMiddleware | Read file snippets (capped at ~50 lines) |
| `file_info` | SootheFilesystemMiddleware | Get file metadata |

**No write tools** — Explore never modifies the filesystem.

### Nodes

#### plan_search
- **Input**: search_target, workspace, accumulated findings (if any)
- **Process**: LLM generates the next search action — which tool, what query, what directory/pattern
- **Output**: Tool call(s) appended to messages
- **Behavior on first call**: Analyzes target intent, generates initial search strategy
- **Behavior on subsequent calls (adjust)**: Refines strategy based on findings so far

#### execute_action
- **Input**: Pending tool calls from plan_search
- **Process**: Executes tool calls against the filesystem backend
- **Output**: Tool results appended to messages, findings updated with discovered paths

#### assess_results
- **Input**: search_target, findings, iterations_used, max_iterations
- **Process**: LLM evaluates whether findings sufficiently answer the target
- **Output**: Decision — "continue" (more of same), "adjust" (new strategy), or "finish" (sufficient results)
- **Forced finish**: If iterations_used >= max_iterations

#### synthesize
- **Input**: All findings
- **Process**: Format top 3-5 matches with descriptions and optional snippets
- **Output**: Final `ExploreResult` as AIMessage
- **Emits**: `soothe.capability.explore.completed` event

### Output Format

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

### Conditional Edge Logic

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

### Events

| Event Type | When | Verbosity Tier |
|-----------|------|---------------|
| `soothe.capability.explore.started` | Search begins | NORMAL |
| `soothe.capability.explore.action` | Tool executed | DETAILED |
| `soothe.capability.explore.assessed` | Assessment result | DETAILED |
| `soothe.capability.explore.completed` | Search complete | NORMAL |

### Prompt Design

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

### Configuration

```yaml
subagents:
  explore:
    enabled: true
    model_role: "default"
    thoroughness: "medium"
    max_iterations:
      quick: 2
      medium: 4
      thorough: 6
    max_read_lines: 50
    max_matches_returned: 5
```

### Plugin Registration

```python
@plugin(name="explore", version="1.0.0", trust_level="built-in")
class ExplorePlugin:
    @subagent(
        name="explore",
        description="Targeted filesystem search agent. Uses iterative LLM-orchestrated search with configurable thoroughness. Best for 'find', 'locate', 'search for' goals.",
        triggers=["find", "locate", "search for", "where is", "look for"],
    )
    async def create_subagent(self, model, config, context):
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
        model: LLM for search planning and result assessment
        config: Soothe configuration
        context: workspace, thoroughness settings

    Returns:
        CompiledSubAgent dict with name, description, runnable
    """
```

### File Structure

```
src/soothe/subagents/explore/
├── __init__.py           # Plugin + exports
├── implementation.py     # Factory function: create_explore_subagent()
├── engine.py             # LangGraph engine builder: build_explore_engine()
├── schemas.py            # ExploreState, MatchEntry, ExploreResult, ExploreConfig
├── events.py             # 4 explore events with register_event()
└── prompts.py            # LLM prompt templates for plan/assess/synthesize
```

### Subagent Registry Update

```python
# In core/resolver/_resolver_tools.py
SUBAGENT_FACTORIES = {
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
    "research": create_research_subagent,
    "explore": create_explore_subagent,  # NEW
}
```

### Integration with AgentLoop

The LLMPlanner prompt gets an update to include explore as an available subagent:

```xml
<AVAILABLE_SUBAGENTS>
- browser: Web automation and browsing
- research: Multi-source research and synthesis
- claude: General-purpose agent with full capabilities
- explore: Targeted filesystem search (quick/medium/thorough)
</AVAILABLE_SUBAGENTS>
```

## Design Decisions

1. **LLM-orchestrated over wave-based** — Adapts to what it finds, avoids unnecessary operations
2. **Thoroughness as iteration cap** — Simple, predictable resource usage control
3. **Read-only tools only** — Explore is a search agent, not a modification agent
4. **No parallel within Explore** — Parallel exploration is a separate concern (future parallel spawning RFC)
5. **Separate RFC from parallel spawning** — RFC-605 splits into two focused RFCs
6. **Follows existing subagent patterns** — Same plugin/factory/event structure as research and browser
7. **Prompts in separate module** — Easier to iterate on search strategy without touching engine logic
8. **Tool reuse** — Uses deepagents' existing `glob`, `grep`, `ls`, `read_file` — no custom implementations

## What Changes from RFC-605

| Aspect | RFC-605 (old) | This Design (new) |
|--------|--------------|-------------------|
| Search strategy | Fixed waves (list→glob→grep) | LLM-orchestrated iterative |
| LLM usage | Strategy + validation | Planning + assessment at each step |
| Thoroughness | max_waves (3) | 3 levels with iteration caps |
| Parallel spawning | Included | Separate RFC |
| StepAction migration | Included | Separate RFC |
| Events | 4 wave-focused events | 4 action-focused events |
| File structure | 6 files + nodes/ subpackage | 6 files (no nodes/ subpackage) |

## Error Handling

1. **LLM plan failure** — Fallback to default search (glob for filename patterns)
2. **Tool execution failure** — Log error, continue to next iteration
3. **No results found** — Return empty matches with summary "No matches found for target"
4. **Iteration budget exceeded** — Force synthesize with whatever findings exist
5. **Read file too large** — Cap at 50 lines, note truncation in findings

## Testing Strategy

### Unit Tests
- `test_plan_search_node` — Mock LLM, verify tool call generation
- `test_execute_action_node` — Mock tools, verify findings update
- `test_assess_results_node` — Mock LLM, verify continue/adjust/finish decisions
- `test_route_after_assessment` — Verify conditional edge logic
- `test_synthesize_node` — Verify output formatting
- `test_thoroughness_caps` — Verify iteration limits per level
- `test_explore_config` — Verify configuration parsing

### Integration Tests
- `test_explore_find_by_name` — Real filesystem, "find auth module"
- `test_explore_find_by_concept` — "how does authentication work"
- `test_explore_quick_thoroughness` — Verify quick search stops early
- `test_explore_thorough_thoroughness` — Verify thorough search reads content
- `test_explore_no_results` — Verify graceful empty results

## Open Questions

1. **Should assess_results be a separate node or part of plan_search?** Currently separate for clarity, but could merge to reduce LLM calls.
2. **Should quick thoroughness skip assess_results entirely?** Would save an LLM call for simple searches.

---

*Explore agent redesign: LLM-orchestrated iterative search replacing fixed wave progression, with configurable thoroughness levels and read-only filesystem tools.*
