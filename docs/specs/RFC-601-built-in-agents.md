# RFC-601: Built-in Plugin Agents

**Status**: Implemented
**Authors**: Soothe Team
**Created**: 2026-03-31
**Last Updated**: 2026-04-05
**Depends on**: RFC-600 (Plugin Extension System), RFC-301 (Protocol Registry)
**Supersedes**: RFC-0004, RFC-0005, RFC-0021
**Kind**: Architecture Design

---

## 1. Abstract

This RFC defines the architecture of Soothe's built-in plugin agent: **Research** (deep information gathering with iterative reflection).

> **Note**: Skillify and Weaver agents have been migrated to the `soothe-community` project as community plugins. Their spec content is maintained in `community/docs/RFC-601-community-agents.md`.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

- Research agent architecture (iterative reflection across sources)
- Plugin definition for the built-in research agent
- Integration contracts with protocols

### 2.2 Non-Goals

This RFC does **not** define:

- Plugin extension system (see RFC-600)
- Protocol interfaces (see RFC-301)
- Event processing (see RFC-400)
- Tool interfaces (see RFC-101)
- Skillify or Weaver agents (see community docs)

---

## 3. Background & Motivation

### 3.1 Why This Is a Subagent

| Characteristic | Tool | Subagent |
|---------------|------|----------|
| Operations | Single-shot | Multi-step workflows |
| State | Stateless | Stateful execution |
| Duration | Immediate | Seconds to minutes |
| Complexity | Simple | Complex orchestration |
| Results | Direct output | Comprehensive reports |

The Research agent exhibits subagent characteristics: multi-step workflows, stateful execution, long-running operations, and complex orchestration.

### 3.2 Design Principles

1. **Self-contained**: Complete package with implementation, events, and configuration
2. **Protocol-first**: Depends on PolicyProtocol via injection
3. **Plugin-compliant**: Follows RFC-600 `@plugin` and `@subagent` decorators
4. **Event-emitting**: Registers and emits domain-specific events

---

## 4. Research Agent

### 4.1 Purpose

Deep research with iterative reflection across multiple information sources. Upgraded from tool to subagent due to multi-step, stateful nature.

### 4.2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  InquiryEngine (CompiledStateGraph)                             │
│                                                                 │
│  analyze → generate_queries → gather → summarize → reflect      │
│      ↑                                              │            │
│      └──────────── iterate (if gaps & loops < max) ─┘           │
│                                                                 │
│  reflect → synthesize → END                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Execution Flow

1. **Analyze topic** → identify sub-questions
2. **Generate queries** → create targeted searches
3. **Route to sources** → select via deterministic routing
4. **Gather information** → execute queries against sources
5. **Summarize results** → integrate gathered info
6. **Reflect** → evaluate completeness, identify gaps
7. **Iterate or synthesize** → if gaps remain: generate follow-up queries, goto 3
8. **Return answer** → comprehensive result with citations

### 4.4 Information Source Protocol

```python
@runtime_checkable
class InformationSource(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def source_type(self) -> SourceType: ...

    async def query(
        self,
        query: str,
        context: GatherContext,
    ) -> list[SourceResult]: ...

    def relevance_score(self, query: str) -> float: ...
```

### 4.5 Built-in Sources

| Source | Type | Purpose | Dependencies |
|--------|------|---------|--------------|
| WebSource | web | Tavily, DuckDuckGo | langchain-community |
| AcademicSource | academic | ArXiv papers | arxiv |
| FilesystemSource | filesystem | Local files | None |
| CLISource | cli | CLI tools | None |
| BrowserSource | browser | Web automation | browser-use |
| DocumentSource | document | PDF/DOCX parsing | pypdf, docx2txt |

### 4.6 Domain Profiles

| Domain | Sources |
|--------|---------|
| web | web, academic |
| code | filesystem, cli |
| deep | all sources |
| auto | router selects by relevance |

### 4.7 Configuration

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

### 4.8 Events

| Event | When |
|-------|------|
| `soothe.subagent.research.analyze` | Topic analysis |
| `soothe.subagent.research.queries_generated` | Queries created |
| `soothe.subagent.research.gather` | Gathering from sources |
| `soothe.subagent.research.reflect` | Reflection on completeness |
| `soothe.subagent.research.synthesize` | Final synthesis |
| `soothe.subagent.research.completed` | Research complete |

---

## 5. Plugin Definition

### 5.1 Research Plugin

```python
@plugin(name="research", version="2.0.0", trust_level="built-in")
class ResearchPlugin:
    @subagent(
        name="research",
        description="Deep research with iterative reflection across sources.",
    )
    async def create_subagent(
        self,
        model,
        config: SootheConfig,
        context: dict,
    ) -> CompiledSubAgent:
        return create_research_subagent(model, config, context)
```

---

## 6. Integration Contracts

### 6.1 PolicyProtocol Usage

| Agent | Action | Check |
|-------|--------|-------|
| Research | `research_query` | Query permission |

### 6.2 Dependencies

| Agent | Depends On |
|-------|------------|
| Research | InformationSource implementations, PolicyProtocol |

---

## 7. File Structure

```
src/soothe/subagents/
└── research/
    ├── __init__.py           # Plugin + exports
    ├── implementation.py     # create_research_subagent()
    ├── events.py             # Research events
    ├── engine.py             # InquiryEngine
    ├── protocol.py           # InformationSource protocol
    ├── router.py             # SourceRouter
    └── sources/              # Source implementations
        ├── web.py
        ├── academic.py
        ├── filesystem.py
        ├── cli.py
        ├── browser.py
        └── document.py
```

---

## 8. Relationship to Other RFCs

- **RFC-600 (Plugin Extension System)**: Plugin decorator patterns
- **RFC-301 (Protocol Registry)**: PolicyProtocol
- **RFC-400 (Event Processing)**: Event emission patterns
- **RFC-100 (CoreAgent Runtime)**: CompiledSubAgent interface
- **RFC-200 (Autonomous Goal Management)**: Goal integration

---

## 9. Open Questions

1. Research: should reflection use separate model role?

---

## 10. Conclusion

This RFC documents Soothe's built-in Research agent:

- **Research**: Deep information gathering with iterative reflection

The agent follows the plugin architecture, integrates with protocols, and demonstrates the subagent pattern for complex workflows.

> **Built-in agents demonstrate the plugin pattern: @plugin + @subagent + self-contained package.**
