# RFC-0021: Research Subagent

**RFC**: 0021
**Title**: Research Subagent
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-26
**Updated**: 2026-03-27
**Replaces**: RFC-0014 (Research Tool)
**Dependencies**: RFC-0001, RFC-0018, RFC-0019

## Abstract

Convert research tool and inquiry module into unified, self-contained research subagent. This RFC consolidates all research functionality into a single package following Soothe's plugin architecture (RFC-0018) and module self-containment principle (RFC-0002). Research upgraded from tool to subagent due to multi-step, stateful, complex nature.

## Problem & Solution

### Problem: Split Architecture

Current architecture separates research into disconnected modules:
- `tools/research/` - Tool wrapper
- `inquiry/` - Core engine and sources

**Issues**: Cross-module dependencies, abstraction mismatch (complex research as tool), incomplete plugin integration, maintenance burden.

### Why Research Should Be a Subagent

**Characteristics**:
- Multi-step workflows: Analyze → Generate Queries → Gather → Summarize → Reflect → Synthesize
- Stateful execution: Accumulates summaries, tracks loops, maintains context
- Long-running: Seconds to minutes
- Complex orchestration: Parallel queries, conditional iteration
- Comprehensive results: Full reports with citations

**Principle**: Tools for single-shot operations; subagents for complex, stateful workflows.

### Goals

Consolidate into `subagents/research/`, convert to subagent API, eliminate cross-module dependencies, follow RFC-0018 plugin pattern, maintain capabilities, enable third-party source registration.

**Non-Goals**: Backward compatibility, algorithm changes, new sources, event system modifications.

## Specification

### Module Structure

```
src/soothe/subagents/research/
├── __init__.py              # Plugin + exports
├── implementation.py        # Subagent factory
├── events.py                # Events (self-registered)
├── engine.py                # InquiryEngine (LangGraph)
├── protocol.py              # InformationSource protocol
├── router.py                # SourceRouter
└── sources/                 # Source implementations
    ├── web.py, academic.py, filesystem.py, cli.py, browser.py, document.py
```

### Plugin Definition

```python
@plugin(name="research", version="2.0.0", description="Deep research subagent", trust_level="built-in")
class ResearchPlugin:
    @subagent(
        name="research",
        description="Deep research with iterative reflection across sources. Inputs: topic (required), domain (auto/web/code/deep). Returns comprehensive answer with citations."
    )
    async def create_subagent(self, model, config, context) -> CompiledSubAgent:
        return create_research_subagent(model, config, context)
```

### InformationSource Protocol

```python
@runtime_checkable
class InformationSource(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def source_type(self) -> SourceType: ...

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]: ...

    def relevance_score(self, query: str) -> float: ...
```

### SourceRouter

Deterministic source selection without LLM calls:

```python
class SourceRouter:
    def select(self, query: str, domain: str = "auto") -> list[InformationSource]:
        """Select best sources based on relevance scores."""
```

### InquiryEngine

```python
def build_inquiry_engine(model, sources, config) -> CompiledStateGraph:
    """Build iterative research graph: analyze → generate_queries → gather → summarize → reflect → [iterate | synthesize] → END"""
```

### Events

Self-registered via `register_event()` (RFC-0019): ResearchAnalyzeEvent, ResearchSubQuestionsEvent, ResearchQueriesGeneratedEvent, ResearchGatherEvent, ResearchGatherDoneEvent, ResearchSummarizeEvent, ResearchReflectEvent, ResearchReflectionDoneEvent, ResearchSynthesizeEvent, ResearchCompletedEvent, ResearchInternalLLMResponseEvent.

### Configuration

```python
class InquiryConfig(BaseModel):
    max_loops: int = 3
    max_sources_per_query: int = 3
    parallel_queries: bool = True
    default_domain: str = "auto"
    enabled_sources: list[SourceType] = ["web", "academic", "filesystem", "cli", "document"]
    source_profiles: dict[str, list[SourceType]] = {
        "web": ["web", "academic"],
        "code": ["filesystem", "cli"],
        "deep": ["web", "academic", "filesystem", "cli", "browser", "document"],
    }
```

### Built-in Sources

| Source | Type | Purpose | Dependencies |
|--------|------|---------|--------------|
| WebSource | web | Tavily, DuckDuckGo | langchain-community |
| AcademicSource | academic | ArXiv papers | arxiv |
| FilesystemSource | filesystem | Local files | None |
| CLISource | cli | CLI tools | None |
| BrowserSource | browser | Web automation (optional) | browser-use |
| DocumentSource | document | PDF/DOCX parsing | pypdf, docx2txt |

**Domain Profiles**: web (web+academic), code (filesystem+cli), deep (all sources), auto (router selects by relevance).

### Execution Flow

1. Analyze topic → identify sub-questions
2. Generate queries → create targeted searches
3. Route to sources → select via deterministic routing
4. Gather information → execute queries against sources
5. Summarize results → integrate gathered info
6. Reflect → evaluate completeness, identify gaps
7. Iterate or synthesize → if gaps & loops < max: generate follow-up queries, goto 3; else: synthesize final answer
8. Return answer → comprehensive result with citations

## Implementation

### Migration Strategy

**Phase 1**: Create `subagents/research/`, copy `inquiry/` contents, copy `tools/research/events.py`.

**Phase 2**: Create `implementation.py`, update plugin with `@subagent`, adapt ResearchTool to CompiledSubAgent.

**Phase 3**: Update imports from `soothe.tools.research`/`soothe.inquiry` to `soothe.subagents.research`.

**Phase 4**: Delete `src/soothe/tools/research/`, `src/soothe/inquiry/`.

**Phase 5**: Move tests to `tests/subagents/research/`.

### Breaking Changes

**Removed**: `soothe.tools.research.*`, `soothe.inquiry.*`

**New**: `soothe.subagents.research.create_research_subagent()`, `ResearchPlugin`

**Migration**:
```python
# OLD: tools = create_research_tools(config); result = tools[0].invoke({"topic": "AI safety"})
# NEW: agent = create_research_subagent(model, config, {}); result = await agent.ainvoke({"messages": [HumanMessage("Research AI safety")]})
```

### Testing

**Unit**: Source isolation, router logic, event registration.

**Integration**: Full workflow, domain selection, reflection iteration.

**Subagent**: CompiledSubAgent compliance, async invocation, state management.

**Plugin**: Plugin loading, subagent creation, event integration.

### Performance

Caching (source-level), parallelism (configurable queries), thread pool (async-to-sync), streaming (partial results).

### Security

Sources within trust boundaries, no arbitrary code execution (except CLISource with constraints), query sanitization via LLM, filesystem access limited to work directories.

## Alternatives Considered

**Keep as Tool**: Rejected - complexity aligns with subagent semantics.

**Tool + Subagent Wrapper**: Rejected - violates self-containment, unnecessary abstraction.

**Split Sources**: Rejected - increases complexity, sources are internal details.

## References

- RFC-0001: System conceptual design
- RFC-0002: Core modules architecture
- RFC-0018: Plugin extension system
- RFC-0019: Event system optimization
- IG-047: Module self-containment
- IG-052: Event system optimization

## Changelog

### 2026-03-26
- Initial RFC
- Research subagent architecture
- Migration strategy

---

*Self-contained research subagent with iterative reflection across multiple information sources.*