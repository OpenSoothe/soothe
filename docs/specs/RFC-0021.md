# RFC-0021: Research Subagent

## Metadata

| Field | Value |
|-------|-------|
| RFC Number | 0021 |
| Title | Research Subagent |
| Status | Draft |
| Type | Architecture Design |
| Created | 2026-03-26 |
| Updated | 2026-03-26 |
| Authors | Claude (AI Agent) |
| Replaces | RFC-0014 (Research Tool - implied) |
| Superseded By | - |
| Dependencies | RFC-0001, RFC-0018, RFC-0019 |

## Abstract

Convert the existing research tool and inquiry module into a unified, self-contained research subagent. This RFC consolidates all research-related functionality into a single package following Soothe's plugin architecture and module self-containment principle. The research capability is upgraded from a tool to a subagent due to its inherently multi-step, stateful, and complex nature.

## Motivation

### Problem Statement

The current architecture separates the research capability into two disconnected modules:
- `tools/research/` - Tool wrapper exposing InquiryEngine
- `inquiry/` - Core research engine and information sources

This violates the module self-containment principle (RFC-0002) and creates several issues:

1. **Cross-module dependencies**: Research tool depends on inquiry module in a different location
2. **Abstraction mismatch**: Research is complex enough to warrant subagent status (iterative loops, stateful execution)
3. **Plugin integration**: Not fully leveraging RFC-0018 plugin decorator patterns
4. **Maintenance burden**: Related code spread across multiple top-level modules

### Why Research Should Be a Subagent

Research exhibits characteristics that align with subagent semantics:

- **Multi-step workflows**: Analyze → Generate Queries → Gather → Summarize → Reflect → Synthesize
- **Stateful execution**: Accumulates summaries, tracks loop counts, maintains context
- **Long-running operations**: Seconds to minutes per invocation
- **Complex orchestration**: Parallel query execution, conditional iteration
- **Comprehensive results**: Returns full reports with citations, not simple values

Tools are appropriate for single-shot operations; subagents are appropriate for complex, stateful workflows.

### Goals

1. Consolidate all research logic into `subagents/research/`
2. Convert from tool API to subagent API
3. Eliminate cross-module dependencies
4. Follow RFC-0018 plugin decorator pattern
5. Maintain all existing research capabilities
6. Enable third-party plugins to register custom research sources

### Non-Goals

1. Backward compatibility with tool API
2. Changing research algorithm or behavior
3. Adding new information sources
4. Modifying event system architecture

## Specification

### Module Structure

```
src/soothe/subagents/research/
├── __init__.py              # Plugin definition + public exports
├── implementation.py        # Research subagent factory
├── events.py                # Research events (self-registered)
├── engine.py                # InquiryEngine (LangGraph implementation)
├── protocol.py              # InformationSource protocol
├── router.py                # SourceRouter (deterministic routing)
└── sources/                 # Information source implementations
    ├── __init__.py
    ├── web.py               # WebSource (Tavily, DuckDuckGo)
    ├── academic.py          # AcademicSource (ArXiv)
    ├── filesystem.py        # FilesystemSource (local files)
    ├── cli.py               # CLISource (CLI tools)
    ├── browser.py           # BrowserSource (browser automation)
    └── document.py          # DocumentSource (PDF, DOCX)
```

### Public API

#### Plugin Definition

```python
from soothe_sdk import plugin, subagent

@plugin(
    name="research",
    version="2.0.0",
    description="Deep research subagent with multi-source synthesis",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research subagent plugin.

    Provides deep research capability with iterative reflection
    across multiple information sources.
    """

    @subagent(
        name="research",
        description=(
            "Deep research subagent that iteratively searches, analyses, and synthesizes "
            "information from multiple sources. Use when a question requires thorough "
            "investigation, cross-validation, or multi-step research beyond a single "
            "web search. "
            "Inputs: `topic` (required, the research question), "
            "`domain` (optional, one of 'auto', 'web', 'code', 'deep'; default 'auto'). "
            "- 'web': Internet research (web search + academic papers). "
            "- 'code': Codebase exploration (filesystem + CLI tools). "
            "- 'deep': All sources combined for comprehensive research. "
            "- 'auto': Automatically selects sources based on the topic. "
            "Returns a comprehensive answer with citations."
        ),
    )
    async def create_subagent(
        self,
        model: BaseChatModel,
        config: SootheConfig,
        context: dict[str, Any],
    ) -> CompiledSubAgent:
        """Create and return the research subagent.

        Args:
            model: LLM for analysis, reflection, and synthesis.
            config: Soothe configuration for model and source setup.
            context: Plugin context with work_dir and other settings.

        Returns:
            Compiled LangGraph subagent.
        """
        return create_research_subagent(model, config, context)
```

#### Subagent Factory

```python
def create_research_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledSubAgent:
    """Create research subagent.

    Args:
        model: LLM for research operations.
        config: Soothe configuration.
        context: Context with work_dir and settings.

    Returns:
        Compiled LangGraph subagent implementing research workflow.
    """
```

### InformationSource Protocol

Internal protocol for queryable information sources:

```python
@runtime_checkable
class InformationSource(Protocol):
    """Protocol for a queryable information source."""

    @property
    def name(self) -> str:
        """Human-readable source name (e.g. 'web_search', 'filesystem')."""
        ...

    @property
    def source_type(self) -> SourceType:
        """Canonical source type for profile-based filtering."""
        ...

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Execute a query against this source.

        Args:
            query: The search query or exploration directive.
            context: Contextual information about the research state.

        Returns:
            List of results, possibly empty if the source found nothing.
        """
        ...

    def relevance_score(self, query: str) -> float:
        """Score how well this source can handle the given query.

        Returns a value in [0.0, 1.0]. Used for deterministic routing.

        Args:
            query: The search query to evaluate.

        Returns:
            Relevance score between 0.0 and 1.0.
        """
        ...
```

### SourceRouter

Deterministic source selection without LLM calls:

```python
class SourceRouter:
    """Routes queries to appropriate sources based on relevance scores."""

    def __init__(self, sources: list[InformationSource], config: InquiryConfig):
        """Initialize router with sources and configuration."""

    def select(self, query: str, domain: str = "auto") -> list[InformationSource]:
        """Select best sources for query.

        Args:
            query: Search query.
            domain: Domain hint ('web', 'code', 'deep', 'auto').

        Returns:
            List of selected sources (max: config.max_sources_per_query).
        """
```

### InquiryEngine

LangGraph-based research workflow:

```python
def build_inquiry_engine(
    model: BaseChatModel,
    sources: list[InformationSource],
    config: InquiryConfig,
) -> CompiledStateGraph:
    """Build iterative research graph.

    Workflow:
      analyze_topic → generate_queries → [route_and_gather] →
      summarize → reflect → [continue | synthesize] → END

    Args:
        model: LLM for research operations.
        sources: Available information sources.
        config: Research configuration.

    Returns:
        Compiled LangGraph runnable.
    """
```

### Events

All events remain unchanged, just relocated:

- `ResearchAnalyzeEvent` - Topic analysis started
- `ResearchSubQuestionsEvent` - Sub-questions identified
- `ResearchQueriesGeneratedEvent` - Search queries generated
- `ResearchGatherEvent` - Information gathering started
- `ResearchGatherDoneEvent` - Gathering completed
- `ResearchSummarizeEvent` - Summarization started
- `ResearchReflectEvent` - Reflection started
- `ResearchReflectionDoneEvent` - Reflection completed
- `ResearchSynthesizeEvent` - Synthesis started
- `ResearchCompletedEvent` - Research completed
- `ResearchInternalLLMResponseEvent` - Internal LLM response

Events are self-registered via `register_event()` following RFC-0019.

### Configuration

```python
class InquiryConfig(BaseModel):
    """Research configuration."""

    max_loops: int = 3  # Maximum reflection iterations
    max_sources_per_query: int = 3  # Maximum sources per query
    parallel_queries: bool = True  # Execute queries in parallel
    default_domain: str = "auto"  # Default source domain
    enabled_sources: list[SourceType] = ["web", "academic", "filesystem", "cli", "document"]
    source_profiles: dict[str, list[SourceType]] = {
        "web": ["web", "academic"],
        "code": ["filesystem", "cli"],
        "deep": ["web", "academic", "filesystem", "cli", "browser", "document"],
    }
```

### Information Sources

#### Built-in Sources

1. **WebSource** - Web search (Tavily, DuckDuckGo)
   - `source_type: "web"`
   - High relevance for: news, current events, general knowledge
   - Dependencies: `langchain-community`

2. **AcademicSource** - ArXiv papers
   - `source_type: "academic"`
   - High relevance for: scientific papers, research topics
   - Dependencies: `arxiv`

3. **FilesystemSource** - Local file exploration
   - `source_type: "filesystem"`
   - High relevance for: code searches, local documents
   - Dependencies: None

4. **CLISource** - CLI tool execution
   - `source_type: "cli"`
   - High relevance for: code analysis, system operations
   - Dependencies: None

5. **BrowserSource** - Browser automation (optional)
   - `source_type: "browser"`
   - High relevance for: interactive web tasks, logged-in sessions
   - Dependencies: `browser-use` (optional extra)

6. **DocumentSource** - PDF/DOCX parsing
   - `source_type: "document"`
   - High relevance for: document analysis
   - Dependencies: `pypdf`, `docx2txt`

### Domain Profiles

- **web**: Web + Academic sources
- **code**: Filesystem + CLI sources
- **deep**: All available sources
- **auto**: Router selects based on query relevance

### Execution Flow

1. **Analyze Topic**: Parse topic, identify sub-questions
2. **Generate Queries**: Create targeted search queries
3. **Route to Sources**: Select sources via deterministic routing
4. **Gather Information**: Execute queries against selected sources
5. **Summarize Results**: Integrate gathered information
6. **Reflect**: Evaluate completeness, identify gaps
7. **Iterate or Synthesize**:
   - If gaps exist and loops < max: Generate follow-up queries, go to step 3
   - Otherwise: Synthesize final answer
8. **Return Answer**: Comprehensive result with citations

## Implementation Notes

### Migration Strategy

1. **Phase 1**: Create new package structure
   - Create `subagents/research/` directory
   - Copy `inquiry/` contents into new package
   - Copy `tools/research/events.py` into new package

2. **Phase 2**: Convert to subagent
   - Create `implementation.py` with `create_research_subagent()`
   - Update plugin definition with `@subagent` decorator
   - Adapt ResearchTool logic to CompiledSubAgent interface

3. **Phase 3**: Update imports
   - Find all imports of `soothe.tools.research`
   - Find all imports of `soothe.inquiry`
   - Update to `soothe.subagents.research`

4. **Phase 4**: Remove old code
   - Delete `src/soothe/tools/research/` package
   - Delete `src/soothe/inquiry/` package

5. **Phase 5**: Update tests
   - Move tests from `tests/tools/research/` to `tests/subagents/research/`
   - Move tests from `tests/inquiry/` to `tests/subagents/research/`
   - Update test imports

### Breaking Changes

**Removed APIs**:
- `soothe.tools.research.ResearchTool`
- `soothe.tools.research.create_research_tools()`
- `soothe.inquiry.*` (entire module)

**New APIs**:
- `soothe.subagents.research.create_research_subagent()`
- `soothe.subagents.research.ResearchPlugin`

**Migration Example**:

```python
# OLD (tool-based)
from soothe.tools.research import create_research_tools

tools = create_research_tools(config, work_dir="/workspace")
result = tools[0].invoke({"topic": "AI safety", "domain": "web"})

# NEW (subagent-based)
from soothe.subagents.research import create_research_subagent
from langchain_core.messages import HumanMessage

agent = create_research_subagent(model, config, {"work_dir": "/workspace"})
result = await agent.ainvoke({
    "messages": [HumanMessage(content="Research AI safety")]
})
answer = result.get("answer")
```

### Testing Requirements

1. **Unit Tests**:
   - Test each information source in isolation
   - Test source router with mock sources
   - Test event registration and emission

2. **Integration Tests**:
   - Test full research workflow with real sources
   - Test domain profile selection
   - Test iterative reflection logic

3. **Subagent Tests**:
   - Test CompiledSubAgent interface compliance
   - Test async invocation
   - Test state management

4. **Plugin Tests**:
   - Test plugin loading via @plugin decorator
   - Test subagent creation via @subagent decorator
   - Test event system integration

### Performance Considerations

- **Caching**: Source-level result caching to avoid redundant queries
- **Parallelism**: Configurable parallel query execution
- **Thread pool**: Shared async-to-sync conversion pool (existing pattern)
- **Streaming**: Support partial results via LangGraph streaming

### Security Considerations

- Sources operate within plugin trust boundaries
- No arbitrary code execution (except CLISource with workspace constraints)
- User-provided queries are sanitized by LLM prompts
- Filesystem access limited to configured work directories

## Alternatives Considered

### Alternative 1: Keep as Tool
**Rejected**: Research complexity (iterative, stateful) aligns better with subagent semantics. Tools are for single-shot operations.

### Alternative 2: Keep Tool + Add Subagent Wrapper
**Rejected**: Violates self-containment principle. Would require maintaining two APIs and add unnecessary abstraction layers.

### Alternative 3: Split Sources into Separate Packages
**Rejected**: Increases complexity and coupling. Sources are internal implementation details of the research capability.

## Open Questions

1. **Q: Should we support custom source registration from third-party plugins?**
   - **A**: Yes, via InformationSource protocol. Plugins can implement their own sources and register them.

2. **Q: How do we handle optional source dependencies (e.g., browser-use)?**
   - **A**: Sources check dependencies at runtime. Missing dependencies result in graceful degradation (source excluded from routing).

3. **Q: Should we expose the source router configuration to users?**
   - **A**: Yes, via InquiryConfig. Users can customize domain profiles and source selection parameters.

## References

- RFC-0001: System Conceptual Design
- RFC-0002: Core Modules Architecture
- RFC-0018: Plugin Extension System
- RFC-0019: Event System Optimization
- IG-047: Module Self-Containment Refactoring
- IG-052: Event System Optimization
- LangGraph Documentation: https://langchain-ai.github.io/langgraph/
- DeepAgents SubAgent API: https://github.com/langchain-ai/deepagents

## Changelog

### 2026-03-26 - RFC-0021 Draft
- Initial RFC draft created
- Defined research subagent architecture
- Specified migration strategy from tool to subagent
- Documented breaking changes and migration path