# Research Subagent Design Draft

## Overview

Convert the existing research tool and inquiry module into a unified, self-contained research subagent following Soothe's plugin architecture and module self-containment principle.

## Current Architecture

### Present Structure
```
src/soothe/
├── tools/research/          # Research tool (exposes InquiryEngine as tool)
│   ├── __init__.py
│   ├── implementation.py    # ResearchTool class
│   └── events.py           # Research events
└── inquiry/                 # Separate inquiry module
    ├── __init__.py
    ├── protocol.py         # InformationSource protocol
    ├── engine.py           # InquiryEngine LangGraph
    ├── router.py           # SourceRouter
    └── sources/            # Information source implementations
        ├── web.py
        ├── academic.py
        ├── filesystem.py
        ├── cli.py
        ├── browser.py
        └── document.py
```

### Issues with Current Design
1. **Tight coupling across modules**: Research tool depends on inquiry module in separate location
2. **Violates self-containment principle**: Inquiry logic is external to the research capability
3. **Tool vs Subagent**: Research is complex enough to warrant subagent status (multi-step, iterative, stateful)
4. **Plugin integration**: Not fully integrated with Soothe's plugin decorator system

## Proposed Architecture

### Target Structure
```
src/soothe/subagents/research/
├── __init__.py              # Plugin definition + exports
├── implementation.py        # Research subagent factory
├── events.py                # Research events (moved from tools/research)
├── engine.py                # InquiryEngine (moved from inquiry/)
├── protocol.py              # InformationSource protocol (moved)
├── router.py                # SourceRouter (moved)
└── sources/                 # Information sources (moved)
    ├── __init__.py
    ├── web.py
    ├── academic.py
    ├── filesystem.py
    ├── cli.py
    ├── browser.py
    └── document.py
```

### Key Design Decisions

#### 1. Tool → Subagent Conversion
**Rationale**: Research is inherently multi-step, stateful, and complex:
- Iterative reflection loops
- Parallel query execution
- State accumulation across iterations
- Long-running operations (seconds to minutes)
- Returns comprehensive results, not simple values

**Approach**: Convert ResearchTool (BaseTool) to ResearchSubagent (CompiledSubAgent):
- Returns `CompiledSubAgent` via `@subagent` decorator
- Uses LangGraph internally (InquiryEngine)
- Maintains conversation state
- Supports streaming and async execution

#### 2. Self-Containment
**Principle**: All research-related logic lives in one package.

**Migration**:
- Move `inquiry/` module entirely into `subagents/research/`
- No external dependencies on `inquiry` module
- Sources become internal implementation details
- Clean plugin boundaries

#### 3. No Backward Compatibility
**Breaking changes**:
- Remove `src/soothe/tools/research/` entirely
- Remove `src/soothe/inquiry/` entirely
- Remove tool-based API (`ResearchTool`)
- Expose only subagent API via plugin decorator

**Migration path**: Users update from:
```python
# OLD (tool)
tools = create_research_tools(config, work_dir)
result = tools[0].invoke({"topic": "AI safety", "domain": "web"})
```

To:
```python
# NEW (subagent)
agent = create_research_subagent(model, config, context)
result = await agent.ainvoke({"messages": [HumanMessage(content="Research AI safety")]})
```

#### 4. Plugin Integration
Follow RFC-0018 plugin pattern:
```python
@plugin(name="research", version="2.0.0", trust_level="built-in")
class ResearchPlugin:
    @subagent(name="research", description="...")
    async def create_subagent(self, model, config, context):
        return create_research_subagent(model, config, context)
```

### Information Sources (Internal)

Sources remain internal implementation details, not exposed publicly:

1. **WebSource**: Web search (Tavily, DuckDuckGo)
2. **AcademicSource**: ArXiv papers
3. **FilesystemSource**: Local file exploration
4. **CLISource**: CLI tool execution
5. **BrowserSource**: Browser automation (optional)
6. **DocumentSource**: PDF/DOCX parsing

Each source implements `InformationSource` protocol with:
- `name: str` - Human-readable name
- `source_type: SourceType` - Type identifier
- `query(query: str, context: GatherContext) -> list[SourceResult]` - Async query
- `relevance_score(query: str) -> float` - Routing score

### Source Router (Internal)

Deterministic routing based on relevance scores:
- No LLM calls for routing
- Domain profiles: "web", "code", "deep", "auto"
- Configurable max sources per query

### Event System

Research events remain the same (moved to new location):
- `ResearchAnalyzeEvent`
- `ResearchSubQuestionsEvent`
- `ResearchQueriesGeneratedEvent`
- `ResearchGatherEvent`
- `ResearchGatherDoneEvent`
- `ResearchSummarizeEvent`
- `ResearchReflectEvent`
- `ResearchReflectionDoneEvent`
- `ResearchSynthesizeEvent`
- `ResearchCompletedEvent`
- `ResearchInternalLLMResponseEvent`

All events self-registered via `register_event()`.

### Configuration

Research subagent configuration:
- `max_loops: int` - Maximum reflection iterations (default: 3)
- `domain: str` - Default source domain (default: "auto")
- `enabled_sources: list[SourceType]` - Available sources
- `parallel_queries: bool` - Execute queries in parallel

Passed via `SootheConfig` or subagent creation parameters.

### Dependencies

**Required**:
- `langchain-core` - Base abstractions
- `langgraph` - Graph-based agent logic
- `deepagents` - Subagent middleware

**Optional** (for sources):
- `langchain-community` - Web search tools
- `arxiv` - Academic papers
- `browser-use` - Browser automation (optional extra)

## Implementation Steps

1. **Create RFC** - Define research subagent specification
2. **Create Implementation Guide** - Detailed migration plan
3. **Move inquiry module** - `inquiry/` → `subagents/research/`
4. **Convert to subagent** - ResearchTool → create_research_subagent
5. **Update plugin** - Use `@subagent` decorator
6. **Update events** - Move to new location, verify registration
7. **Remove old code** - Delete `tools/research/` and `inquiry/`
8. **Update tests** - Migrate tests to new structure
9. **Update imports** - Fix all imports across codebase
10. **Verify** - Run full test suite

## Testing Strategy

1. **Unit tests**: Test each source in isolation
2. **Integration tests**: Test full research workflow
3. **Event tests**: Verify event emission and registration
4. **Subagent tests**: Test CompiledSubAgent interface
5. **Plugin tests**: Test plugin loading and subagent creation

## Migration Impact

### Removed Modules
- `src/soothe/tools/research/` (entire package)
- `src/soothe/inquiry/` (entire package)

### New Module
- `src/soothe/subagents/research/` (new unified package)

### Updated Imports
- All imports of `soothe.tools.research` → `soothe.subagents.research`
- All imports of `soothe.inquiry` → `soothe.subagents.research`

### Config Changes
- None (config remains compatible)

### API Changes
- Tool API removed, Subagent API added
- Users must update to subagent invocation pattern

## Benefits

1. **Self-containment**: All research logic in one place
2. **Better abstraction**: Subagent for complex multi-step workflows
3. **Clean plugin boundaries**: Follows RFC-0018 pattern
4. **Simpler architecture**: No cross-module dependencies
5. **Easier maintenance**: Single package to understand and test

## Risks

1. **Breaking change**: No backward compatibility
2. **Import updates**: Many files need import path changes
3. **Test migration**: Tests need restructuring
4. **User migration**: Users must update their code

## Success Criteria

1. All research logic in `subagents/research/`
2. No references to old `tools/research/` or `inquiry/`
3. All tests pass (900+ tests)
4. Linting passes with zero errors
5. Events properly registered and emitted
6. Subagent successfully created via plugin decorator
7. Full research workflow functional

## Timeline

- Phase 1 (RFC): 1 day
- Phase 2 (Implementation): 2-3 days
- Phase 3 (Review): 1 day

## References

- RFC-0001: System Conceptual Design
- RFC-0018: Plugin Extension System
- IG-047: Module Self-Containment Refactoring
- IG-052: Event System Optimization