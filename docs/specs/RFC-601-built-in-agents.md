# RFC-601: Built-in Plugin Agents

**Status**: Implemented
**Authors**: Soothe Team
**Created**: 2026-03-31
**Last Updated**: 2026-03-31
**Depends on**: RFC-600 (Plugin Extension System), RFC-301 (Protocol Registry)
**Supersedes**: RFC-0004, RFC-0005, RFC-0021
**Kind**: Architecture Design

---

## 1. Abstract

This RFC defines the architecture of Soothe's built-in plugin agents: Skillify (skill indexing and retrieval), Weaver (generative agent composition), and Research (deep information gathering). These agents follow the plugin architecture defined in RFC-600 and demonstrate the subagent pattern for complex, stateful workflows.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* Skillify agent architecture (background indexing, retrieval subagent)
* Weaver agent architecture (reuse-first generation, skill harmonization)
* Research agent architecture (iterative reflection across sources)
* Plugin definitions for each built-in agent
* Integration contracts with protocols

### 2.2 Non-Goals

This RFC does **not** define:

* Plugin extension system (see RFC-600)
* Protocol interfaces (see RFC-301)
* Event processing (see RFC-401)
* Tool interfaces (see RFC-101)

---

## 3. Background & Motivation

### 3.1 Why These Are Subagents

| Characteristic | Tool | Subagent |
|---------------|------|----------|
| Operations | Single-shot | Multi-step workflows |
| State | Stateless | Stateful execution |
| Duration | Immediate | Seconds to minutes |
| Complexity | Simple | Complex orchestration |
| Results | Direct output | Comprehensive reports |

All three built-in agents exhibit subagent characteristics: multi-step workflows, stateful execution, long-running operations, and complex orchestration.

### 3.2 Design Principles

1. **Self-contained**: Each agent is a complete package with implementation, events, and configuration
2. **Protocol-first**: Depend on VectorStoreProtocol, PolicyProtocol via injection
3. **Plugin-compliant**: Follow RFC-600 `@plugin` and `@subagent` decorators
4. **Event-emitting**: Register and emit domain-specific events

---

## 4. Skillify Agent

### 4.1 Purpose

Semantic indexing and retrieval of skill packages from a warehouse. Operates as two decoupled concerns:

* **Background indexing loop**: Continuously curates vector index of SKILL.md-compliant packages
* **Retrieval CompiledSubAgent**: Serves on-demand skill bundles

### 4.2 Architecture

```
┌──────────────────────────────────────────────────────────┐
│  SkillIndexer (asyncio.Task)                             │
│                                                          │
│  loop:                                                   │
│    1. ensure_collection() / bootstrap_hash_cache()       │
│    2. SkillWarehouse.scan() → list[SkillRecord]          │
│    3. For each record:                                   │
│       a. Compare content_hash with cached hash           │
│       b. If changed or new: embed → upsert VectorStore   │
│    4. Delete vector records no longer present on disk    │
│    5. Emit soothe.subagent.skillify.* index events       │
│    6. Sleep(index_interval_seconds)                      │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  SkillRetriever (CompiledSubAgent)                       │
│                                                          │
│  [START] → retrieve → [END]                              │
│                                                          │
│  retrieve:                                               │
│    1. Extract query from messages                        │
│    2. Wait for indexing readiness (bounded)              │
│    3. Embed query                                        │
│    4. VectorStoreProtocol.search()                       │
│    5. Return SkillBundle                                 │
└──────────────────────────────────────────────────────────┘
```

### 4.3 Data Models

```python
class SkillRecord(BaseModel):
    id: str                        # SHA-256(path)[:16]
    name: str                      # from SKILL.md frontmatter
    description: str               # from SKILL.md frontmatter
    path: str                      # absolute filesystem path
    tags: list[str] = []
    status: Literal["indexed", "stale", "error"] = "indexed"
    indexed_at: datetime
    content_hash: str              # SHA-256 of SKILL.md

class SkillBundle(BaseModel):
    query: str
    results: list[SkillSearchResult]
    total_indexed: int
```

### 4.4 Configuration

```python
class SkillifyConfig(BaseModel):
    enabled: bool = False
    warehouse_paths: list[str] = []
    index_interval_seconds: int = 300
    index_collection: str = "soothe_skillify"
    retrieval_top_k: int = 10
```

### 4.5 Events

| Event | When |
|-------|------|
| `soothe.subagent.skillify.index_started` | Background indexing started |
| `soothe.subagent.skillify.index_updated` | Indexing pass with changes |
| `soothe.subagent.skillify.retrieve_started` | Retrieval request received |
| `soothe.subagent.skillify.retrieve_completed` | Results returned |

---

## 5. Weaver Agent

### 5.1 Purpose

Generative agent composition that combines skills, tools, and MCP capabilities into instant subagents. Implements reuse-first strategy with skill harmonization pipeline.

### 5.2 Architecture

```
[START] → weave → [END]

weave node phases:
  1. Analyze request → CapabilitySignature
  2. Check reuse index → ReuseCandidate (if above threshold, skip generation)
  3. Fetch skills from Skillify
  4. Harmonize skills (conflict detection → merge → gap analysis)
  5. Resolve tools
  6. Generate agent package
  7. Validate package
  8. Register and upsert reuse index
  9. Execute agent inline
```

### 5.3 Skill Harmonization Pipeline

**Step 1: Conflict Detection**

Analyze candidate skills for pairwise contradictions. Output: `SkillConflictReport`.

**Step 2: Deduplication and Merging**

For overlaps: select best-fit or merge. For conflicts: apply resolution. Output: deduplicated skill set.

**Step 3: Gap Analysis**

Identify missing connective logic (bridge instructions). Output: glue instructions for system prompt.

### 5.4 Data Models

```python
class CapabilitySignature(BaseModel):
    description: str
    required_capabilities: list[str]
    constraints: list[str]
    expected_input: str
    expected_output: str

class AgentManifest(BaseModel):
    name: str
    description: str
    type: Literal["subagent"] = "subagent"
    system_prompt_file: str = "system_prompt.md"
    skills: list[str] = []
    tools: list[str] = []
    capabilities: list[str] = []
    created_at: datetime
    version: int = 1

class HarmonizedSkillSet(BaseModel):
    skills: list[str]
    skill_contents: dict[str, str]
    bridge_instructions: str
    dropped_skills: list[str]
    merge_log: list[str]
```

### 5.5 Configuration

```python
class WeaverConfig(BaseModel):
    enabled: bool = False
    generated_agents_dir: str = ""  # default: SOOTHE_HOME/generated_agents
    reuse_threshold: float = 0.85
    reuse_collection: str = "soothe_weaver_reuse"
    max_generation_attempts: int = 2
    allowed_tool_groups: list[str] = []
    allowed_mcp_servers: list[str] = []
```

### 5.6 Events

| Event | When |
|-------|------|
| `soothe.subagent.weaver.analysis_completed` | Capability signature extracted |
| `soothe.subagent.weaver.reuse_hit` | Existing agent matched |
| `soothe.subagent.weaver.reuse_miss` | No suitable existing agent |
| `soothe.subagent.weaver.harmonize_completed` | Skill harmonization done |
| `soothe.subagent.weaver.generate_completed` | Agent package written |
| `soothe.subagent.weaver.execute_completed` | Execution done |

---

## 6. Research Agent

### 6.1 Purpose

Deep research with iterative reflection across multiple information sources. Upgraded from tool to subagent due to multi-step, stateful nature.

### 6.2 Architecture

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

### 6.3 Execution Flow

1. **Analyze topic** → identify sub-questions
2. **Generate queries** → create targeted searches
3. **Route to sources** → select via deterministic routing
4. **Gather information** → execute queries against sources
5. **Summarize results** → integrate gathered info
6. **Reflect** → evaluate completeness, identify gaps
7. **Iterate or synthesize** → if gaps remain: generate follow-up queries, goto 3
8. **Return answer** → comprehensive result with citations

### 6.4 Information Source Protocol

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

### 6.5 Built-in Sources

| Source | Type | Purpose | Dependencies |
|--------|------|---------|--------------|
| WebSource | web | Tavily, DuckDuckGo | langchain-community |
| AcademicSource | academic | ArXiv papers | arxiv |
| FilesystemSource | filesystem | Local files | None |
| CLISource | cli | CLI tools | None |
| BrowserSource | browser | Web automation | browser-use |
| DocumentSource | document | PDF/DOCX parsing | pypdf, docx2txt |

### 6.6 Domain Profiles

| Domain | Sources |
|--------|---------|
| web | web, academic |
| code | filesystem, cli |
| deep | all sources |
| auto | router selects by relevance |

### 6.7 Configuration

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

### 6.8 Events

| Event | When |
|-------|------|
| `soothe.subagent.research.analyze` | Topic analysis |
| `soothe.subagent.research.queries_generated` | Queries created |
| `soothe.subagent.research.gather` | Gathering from sources |
| `soothe.subagent.research.reflect` | Reflection on completeness |
| `soothe.subagent.research.synthesize` | Final synthesis |
| `soothe.subagent.research.completed` | Research complete |

---

## 7. Plugin Definitions

### 7.1 Skillify Plugin

```python
@plugin(name="skillify", version="1.0.0", trust_level="built-in")
class SkillifyPlugin:
    @subagent(
        name="skillify",
        description="Semantic skill indexing and retrieval.",
    )
    async def create_subagent(
        self,
        model,
        config: SootheConfig,
        context: dict,
    ) -> CompiledSubAgent:
        return create_skillify_subagent(model, config, context)
```

### 7.2 Weaver Plugin

```python
@plugin(name="weaver", version="1.0.0", trust_level="built-in")
class WeaverPlugin:
    @subagent(
        name="weaver",
        description="Generative agent composition from skills.",
    )
    async def create_subagent(
        self,
        model,
        config: SootheConfig,
        context: dict,
    ) -> CompiledSubAgent:
        return create_weaver_subagent(model, config, context)
```

### 7.3 Research Plugin

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

## 8. Integration Contracts

### 8.1 VectorStoreProtocol Usage

| Agent | Collection | Purpose |
|-------|------------|---------|
| Skillify | `soothe_skillify` | Skill embeddings |
| Weaver | `soothe_weaver_reuse` | Generated agent reuse index |

### 8.2 PolicyProtocol Usage

| Agent | Action | Check |
|-------|--------|-------|
| Skillify | `skillify_retrieve` | Retrieval permission |
| Weaver | `weaver_generate` | Generation permission |
| Research | `research_query` | Query permission |

### 8.3 Dependencies

| Agent | Depends On |
|-------|------------|
| Skillify | VectorStoreProtocol, Embeddings |
| Weaver | Skillify (optional), VectorStoreProtocol, PolicyProtocol |
| Research | InformationSource implementations, PolicyProtocol |

---

## 9. File Structure

```
src/soothe/subagents/
├── skillify/
│   ├── __init__.py           # Plugin + exports
│   ├── implementation.py     # create_skillify_subagent()
│   ├── events.py             # Skillify events
│   ├── indexer.py            # SkillIndexer
│   ├── retriever.py          # Retrieval logic
│   ├── warehouse.py          # Skill scanning
│   └── models.py             # SkillRecord, SkillBundle
├── weaver/
│   ├── __init__.py           # Plugin + exports
│   ├── implementation.py     # create_weaver_subagent()
│   ├── events.py             # Weaver events
│   ├── composer.py           # AgentComposer
│   ├── harmonizer.py         # Skill harmonization
│   ├── registry.py           # GeneratedAgentRegistry
│   └── models.py             # CapabilitySignature, AgentManifest
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

## 10. Relationship to Other RFCs

* **RFC-600 (Plugin Extension System)**: Plugin decorator patterns
* **RFC-301 (Protocol Registry)**: VectorStoreProtocol, PolicyProtocol
* **RFC-401 (Event Processing)**: Event emission patterns
* **RFC-100 (CoreAgent Runtime)**: CompiledSubAgent interface
* **RFC-200 (Autonomous Goal Management)**: Goal integration

---

## 11. Open Questions

1. Should Skillify support incremental indexing of large warehouses?
2. Weaver MCP server wiring not implemented — when needed?
3. Research: should reflection use separate model role?

---

## 12. Conclusion

This RFC documents Soothe's three built-in plugin agents:

- **Skillify**: Skill warehouse indexing and semantic retrieval
- **Weaver**: Generative agent composition with skill harmonization
- **Research**: Deep information gathering with iterative reflection

Each follows the plugin architecture, integrates with protocols, and demonstrates the subagent pattern for complex workflows.

> **Built-in agents demonstrate the plugin pattern: @plugin + @subagent + self-contained package.**