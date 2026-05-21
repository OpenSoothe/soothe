# RFC-619: Tacitus Subagent (Public-Domain Research)

**RFC**: 619  
**Title**: Tacitus Subagent  
**Status**: Accepted  
**Kind**: Architecture Design  
**Created**: 2026-05-21  
**Authors**: Soothe Team  
**Depends on**: RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming)  
**Supersedes**: Research subagent identity and local-source gather paths in RFC-601 §4  

---

## 1. Abstract

**Tacitus** replaces the built-in **research** subagent as Soothe's public-domain investigation agent. It iteratively gathers, summarizes, and synthesizes information from **outbound sources only** (web search, Wikipedia, academic corpora, public URLs). Repository exploration and shell execution remain the responsibility of **explore** and the main agent.

---

## 2. Scope

### 2.1 In scope

- Subagent id `tacitus` (plugin name, config key, `task` `subagent_type`)
- Public information capabilities and semantic source routing
- Wire events `soothe.subagent.tacitus.*`
### 2.2 Non-goals

- Local filesystem, shell, or document-QA gather (removed from this subagent)
- Keyword-based routing or query gating
- Browser automation (future separate RFC)

---

## 3. Motivation

| Issue (research) | Tacitus response |
|------------------|------------------|
| Overlaps explore (fs/cli/document) | Public-only boundary |
| Keyword `relevance_score` / gates | Sentence-transformer routing + always-run selected sources |
| Monolithic WebSource + conditional Wikipedia | Separate capability adapters |
| Id "research" conflicts with generic English | Distinct id `tacitus` |

---

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ TacitusEngine (LangGraph)                                    │
│ analyze → generate_queries → gather → summarize → reflect   │
│      ↑                                    │                  │
│      └──────── iterate ──────────────────┘                  │
│                      ↓ sufficient                            │
│                   synthesize → END                           │
└─────────────────────────────────────────────────────────────┘
                              │
                    PublicSemanticRouter
                              │
        ┌─────────────┬───────┴────────┬──────────────┐
        ▼             ▼                ▼              ▼
   web_search    wikipedia      academic_search   url_crawl
   (wizsearch)  (langchain)      (deepxiv)      (wizsearch)
```

### 4.1 Capability model

Each capability is a thin `PublicInformationSource` with:

- `capability_id`: stable router key
- `capability_description`: fixed text embedded once for semantic routing
- `query()`: invokes one toolkit; no keyword pre-gate

| capability_id | Tooling | Purpose |
|---------------|---------|---------|
| `web_search` | `WizsearchSearchTool` | Multi-engine web search |
| `wikipedia` | `WikipediaQueryRun` | Encyclopedia / definitions |
| `academic_search` | `DeepxivSearchTool` | Semantic paper search |
| `url_crawl` | `WizsearchCrawlTool` | Extract content from explicit URLs |

**Fast-paths (regex only, not NL keywords):**

- HTTP(S) URL in query → include `url_crawl`
- arXiv/PMC id pattern → boost `academic_search`

### 4.2 Routing

- **Primary**: cosine similarity between query embedding and precomputed capability embeddings (`sentence_transformers` / `all-MiniLM-L6-v2` via `soothe.utils.similarity`)
- **Fallback**: when model not cached locally, uniform eligibility (all profile capabilities) or optional fast-LLM batch classify (implementation detail in IG-425)
- **No** `keyword_score` in router or gather gates

Domain profiles:

| Domain | Capabilities |
|--------|----------------|
| `public` (default) | all four |
| `web` | `web_search`, `wikipedia`, `url_crawl` |
| `academic` | `academic_search`, `wikipedia` |

Deprecated domains `code`, `deep`, `auto` map to `public`.

### 4.3 Post-gather ranking

Before summarize, rank `SourceResult` snippets with `async_semantic_similarity(query, content)` when embeddings are available.

---

## 5. Plugin and integration

```python
@plugin(name="tacitus", version="3.0.0", trust_level="built-in")
class TacitusPlugin:
    @subagent(name="tacitus", triggers=["TACITUS_RULES", "context"])
    async def create_subagent(...):
        return create_tacitus_subagent(...)
```

- Resolver factory key: `tacitus`
- Discovery: `soothe.subagents.tacitus`
- Config: `subagents.tacitus` in YAML
- Slash: `/tacitus`

---

## 6. Wire events

| Event type | Fields |
|------------|--------|
| `soothe.subagent.tacitus.started` | `topic_preview` |
| `soothe.subagent.tacitus.gather.summary` | `query_preview`, `result_count`, `sources_touched` |
| `soothe.subagent.tacitus.completed` | `duration_ms`, `answer_length`, `summary` |

---

## 7. Relationship to other agents

| Agent | Use when |
|-------|----------|
| **tacitus** | Public facts, papers, web docs, cross-source synthesis |
| **explore** | Codebase search, local files, repo structure |
| **plan** | Planning and evidence collection for goals |

---

## 8. Conclusion

Tacitus is the built-in **public-domain** research subagent: clearer boundaries, semantic routing, and a stable id. RFC-601 Research section is superseded for identity and source scope by this RFC.
