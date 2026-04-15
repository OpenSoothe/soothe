# RFC-601 (Community): Skillify and Weaver Agents

**Status**: Implemented (Community Plugin)
**Package**: `soothe-community`
**Created**: 2026-03-31 (originally in main RFC-601)
**Migrated**: 2026-04-05 (moved to community per RFC-600)
**Depends on**: RFC-600 (Plugin Extension System), RFC-301 (Protocol Registry)
**Kind**: Architecture Design

---

## 1. Abstract

This RFC defines the architecture of two community plugin agents for Soothe: **Skillify** (skill indexing and retrieval) and **Weaver** (generative agent composition). These agents are distributed via the `soothe-community` package and loaded through RFC-600 entry-point discovery.

---

## 2. Scope

This RFC defines:
- Skillify agent architecture (background indexing, retrieval subagent)
- Weaver agent architecture (reuse-first generation, skill harmonization)
- Plugin definitions for both community agents
- Integration contracts with protocols
- Cross-plugin dependency (Weaver depends on Skillify)

---

## 3. Skillify Agent

### 3.1 Purpose

Semantic indexing and retrieval of skill packages from a warehouse. Operates as two decoupled concerns:

- **Background indexing loop**: Continuously curates vector index of SKILL.md-compliant packages
- **Retrieval CompiledSubAgent**: Serves on-demand skill bundles

### 3.2 Architecture

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

### 3.3 Data Models

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

### 3.4 Plugin Definition

```python
@plugin(
    name="skillify",
    version="1.0.0",
    description="Skill warehouse indexing and semantic retrieval",
    dependencies=["langgraph>=0.2.0"],
    trust_level="standard",
)
class SkillifyPlugin:
    @subagent(name="skillify", description="Semantic skill indexing and retrieval.")
    async def create_skillify(self, model, config, context):
        return create_skillify_subagent(model, config, context)
```

### 3.5 Events

| Event | When |
|-------|------|
| `soothe.subagent.skillify.index_started` | Background indexing started |
| `soothe.subagent.skillify.index_updated` | Indexing pass with changes |
| `soothe.subagent.skillify.index_unchanged` | Indexing pass, no changes |
| `soothe.subagent.skillify.index_failed` | Indexing error |
| `soothe.subagent.skillify.retrieve_started` | Retrieval request received |
| `soothe.subagent.skillify.retrieve_completed` | Results returned |
| `soothe.subagent.skillify.retrieve_not_ready` | Index not yet ready |
| `soothe.subagent.skillify.indexing_pending` | Indexing in progress |

---

## 4. Weaver Agent

### 4.1 Purpose

Generative agent composition that combines skills, tools, and MCP capabilities into instant subagents. Implements reuse-first strategy with skill harmonization pipeline.

### 4.2 Architecture

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

### 4.3 Skill Harmonization Pipeline

**Step 1: Conflict Detection**

Analyze candidate skills for pairwise contradictions. Output: `SkillConflictReport`.

**Step 2: Deduplication and Merging**

For overlaps: select best-fit or merge. For conflicts: apply resolution. Output: deduplicated skill set.

**Step 3: Gap Analysis**

Identify missing connective logic (bridge instructions). Output: glue instructions for system prompt.

### 4.4 Data Models

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

### 4.5 Plugin Definition

```python
@plugin(
    name="weaver",
    version="1.0.0",
    description="Generative agent framework with skill harmonization",
    dependencies=["langgraph>=0.2.0"],
    trust_level="standard",
)
class WeaverPlugin:
    @subagent(name="weaver", description="Generative agent composition from skills.")
    async def create_weaver(self, model, config, context):
        return create_weaver_subagent(model, config, context)
```

### 4.6 Events

| Event | When |
|-------|------|
| `soothe.subagent.weaver.dispatched` | Task dispatched |
| `soothe.subagent.weaver.analysis_started` | Capability analysis begun |
| `soothe.subagent.weaver.analysis_completed` | Capability signature extracted |
| `soothe.subagent.weaver.reuse_hit` | Existing agent matched |
| `soothe.subagent.weaver.reuse_miss` | No suitable existing agent |
| `soothe.subagent.weaver.skillify_pending` | Waiting for Skillify index |
| `soothe.subagent.weaver.harmonize_started` | Skill harmonization begun |
| `soothe.subagent.weaver.harmonize_completed` | Harmonization done |
| `soothe.subagent.weaver.generate_started` | Agent generation begun |
| `soothe.subagent.weaver.generate_completed` | Agent package written |
| `soothe.subagent.weaver.validate_started` | Validation begun |
| `soothe.subagent.weaver.validate_completed` | Validation done |
| `soothe.subagent.weaver.registry_updated` | Agent registered |
| `soothe.subagent.weaver.execute_started` | Execution begun |
| `soothe.subagent.weaver.execute_completed` | Execution done |
| `soothe.subagent.weaver.completed` | Full workflow complete |

---

## 5. Integration Contracts

### 5.1 VectorStoreProtocol Usage

| Agent | Collection | Purpose |
|-------|------------|---------|
| Skillify | `soothe_skillify` | Skill embeddings |
| Weaver | `soothe_weaver_reuse` | Generated agent reuse index |

### 5.2 PolicyProtocol Usage

| Agent | Action | Check |
|-------|--------|-------|
| Skillify | `skillify_retrieve` | Retrieval permission |
| Weaver | `weaver_generate` | Generation permission |

### 5.3 Dependencies

| Agent | Depends On |
|-------|------------|
| Skillify | VectorStoreProtocol, Embeddings |
| Weaver | Skillify (optional), VectorStoreProtocol, PolicyProtocol |

### 5.4 Cross-Plugin Dependency

Weaver imports from Skillify:
- `soothe_community.skillify.models.SkillBundle` — used during skill fetching
- `soothe_community.skillify.retriever.SkillRetriever` — used to retrieve skills during agent composition

Weaver verifies Skillify availability at load time in `on_load()`:

```python
async def on_load(self, context):
    try:
        from soothe_community.skillify.models import SkillBundle
    except ImportError:
        raise PluginError("Weaver requires Skillify plugin.", plugin_name="weaver")
```

---

## 6. File Structure (Community)

```
community/src/soothe_community/
├── skillify/
│   ├── __init__.py           # SkillifyPlugin + exports
│   ├── events.py             # Skillify events
│   ├── indexer.py            # SkillIndexer
│   ├── retriever.py          # Retrieval logic
│   ├── warehouse.py          # Skill scanning
│   └── models.py             # SkillRecord, SkillBundle
└── weaver/
    ├── __init__.py           # WeaverPlugin + exports
    ├── events.py             # Weaver events
    ├── analyzer.py           # RequirementAnalyzer
    ├── composer.py           # AgentComposer (harmonization)
    ├── generator.py          # AgentGenerator
    ├── registry.py           # GeneratedAgentRegistry
    ├── reuse.py              # ReuseIndex
    └── models.py             # CapabilitySignature, AgentManifest
```

---

## 7. Installation

```bash
pip install soothe-community
```

Plugins are auto-discovered via entry points in `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
skillify = "soothe_community.skillify:SkillifyPlugin"
weaver = "soothe_community.weaver:WeaverPlugin"
```

---

## 8. Relationship to Other RFCs

- **RFC-600 (Plugin Extension System)**: Plugin decorator patterns, entry-point discovery
- **RFC-301 (Protocol Registry)**: VectorStoreProtocol, PolicyProtocol
- **RFC-401 (Event Processing)**: Event emission patterns
- **RFC-100 (CoreAgent Runtime)**: CompiledSubAgent interface

---

## 9. Open Questions

1. Should Skillify support incremental indexing of large warehouses?
2. Weaver MCP server wiring not implemented — when needed?
3. Should Weaver's generated agent registry support remote storage?

---

## 10. Conclusion

This RFC documents two community plugin agents for Soothe:

- **Skillify**: Skill warehouse indexing and semantic retrieval
- **Weaver**: Generative agent composition with skill harmonization

Both follow the RFC-600 plugin architecture with `@plugin` + `@subagent` decorators, self-contained package structure, and entry-point discovery via `soothe-community`.

> **Community agents demonstrate the plugin pattern: @plugin + @subagent + self-contained package.**
