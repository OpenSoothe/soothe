# RFC-619: Deep Research Subagent

**RFC**: 619  
**Title**: Deep Research Subagent  
**Status**: Accepted (revised)  
**Kind**: Architecture Design  
**Created**: 2026-05-21  
**Updated**: 2026-07-07  
**Authors**: Soothe Team  
**Depends on**: RFC-600 (Plugin Extension System), RFC-601 (Built-in Agents), RFC-403 (Unified Event Naming), RFC-616 (Scenario-Driven Synthesis)  
**Supersedes**: Deep Research subagent identity (prior RFC-619 revision), Research section identity in RFC-601 §4  

### Change history

| Date | Change |
|------|--------|
| 2026-05-21 | Initial Deep Research subagent (public-domain multi-source research) |
| 2026-07-07 | **Revised**: Split monolithic research subagent into `deep_research` (web-only, crawl-on-discovery, adaptive report) and `academic_research`. Clean break — no legacy aliases. |

---

## 1. Abstract

**`deep_research`** is Soothe's built-in subagent for **iterative public web research**. It searches the web, crawls discovered URLs, reflects on evidence gaps, and produces an **adaptive research report** (RFC-616 pattern). Local repository analysis uses the main agent's file tools. Academic literature review uses the separate **`academic_research`** subagent.

**Clean break**: The prior monolithic research subagent id, config keys, events, and package are removed. No backward-compatibility shims.

---

## 2. Scope

### 2.1 In scope (phase 1)

- Subagent id `deep_research` (plugin name, config key, `task` `subagent_type`)
- Public **web search** capability only
- **Crawl-on-discovery**: top-N URLs from each search result set
- Shared **`url_crawl`** toolkit (extracted to `toolkits/url_crawl/`)
- Research-native **ReportScenarioClassifier** and adaptive report synthesis
- Wire events `soothe.subagent.deep_research.*`
- Effort levels: `normal` | `thorough`

### 2.2 Phase 2 — `academic_research` (implemented)

- Subagent id `academic_research` — academic sources only + shared `url_crawl`
- Separate package at `subagents/academic_research/`

### 2.3 Non-goals

- Local filesystem, shell, or document-QA gather
- Browser automation (see `browser_use`)
- Backward-compatible legacy research subagent config, slash routes, or event aliases
- Keyword-based query gating

---

## 3. Motivation

| Issue (prior monolithic research agent) | `deep_research` response |
|-------------------------|--------------------------|
| Id sounds generic ("deep research" vs local research) | Explicit id `deep_research` for public web investigation |
| Web + academic + url in one agent | Web-only; academic split to `academic_research` |
| Answer-style output | Adaptive report (RFC-616 pattern, IG-552 format hints) |
| Confusion with local repo analysis | Hybrid boundary + mandatory Scope banner; local files on main agent |
| Stale `explore` references | Local recon via main agent file tools (IG-547) |

---

## 4. Subagent boundaries

| Concern | Owner |
|---------|--------|
| Public web facts, comparisons, how-tos, industry landscape | `deep_research` |
| Local repo / codebase analysis | Main agent (`read_file`, `grep`, `glob`, `ls`) |
| Academic papers, literature review | `academic_research` |

**Hybrid rule**: When a goal mentions the user's project (e.g. "how does our auth compare to industry practice?"), `deep_research` searches the **public web** for external knowledge. The main agent handles local code analysis. Every report states this in a **Scope** section (see §6).

---

## 5. Architecture (phase 1)

### 5.1 Package layout

```
packages/soothe/src/soothe/
├── toolkits/url_crawl/           # shared crawl + polite HTTP
└── subagents/deep_research/
    ├── __init__.py               # @plugin(name="deep_research")
    ├── implementation.py
    ├── engine.py                 # LangGraph loop
    ├── protocol.py               # DeepResearchConfig
    ├── effort.py                 # normal | thorough
    ├── report_classifier.py
    ├── events.py
    └── sources/web_search.py
```

### 5.2 Engine flow

```
plan → gather (web search) → crawl (top N URLs) → reflect → [iterate] → classify report → synthesize → END
```

```
┌──────────────────────────────────────────────────────────────────┐
│ DeepResearchEngine (LangGraph)                                    │
│ plan → gather → crawl → reflect                                  │
│      ↑                    │                                       │
│      └──── iterate ───────┘                                       │
│                           ↓ sufficient                            │
│              classify report scenario → synthesize → END            │
└──────────────────────────────────────────────────────────────────┘
         │                    │
    web_search          url_crawl (toolkit)
```

**Crawl-on-discovery**: After each web search, automatically crawl the top N result URLs (configurable per effort level) before reflect/synthesize.

### 5.3 Effort profiles

| Setting | `normal` | `thorough` |
|---------|----------|------------|
| Max loops | 2 | 4 |
| Max queries per loop | 4 | 8 |
| Crawl top-N per search | 3 | 5 |
| Primary LLM role | `fast` | `fast` |
| Synthesis role | `fast` | `fast` (optional `think` via config) |

Config: `subagents.deep_research.config.effort: normal | thorough`

### 5.4 Web search source

Single `PublicInformationSource` adapter:

| capability_id | Tooling | Purpose |
|---------------|---------|---------|
| `web_search` | `WizsearchSearchTool` (+ Tavily/DuckDuckGo fallbacks) | Multi-engine public web search |

No semantic multi-source router in phase 1 — web search only. URL crawl is a post-search step, not a routed capability.

### 5.5 Shared url_crawl toolkit

Extracted from the prior research implementation:

- Polite HTTP (rate limiting, circuit breaker)
- `crawl_urls(urls, *, max_concurrent, timeout_sec) -> list[CrawlResult]`
- Used by `deep_research` (phase 1) and `academic_research` (phase 2)

---

## 6. Adaptive report

### 6.1 ReportScenarioClassifier

Research-native classifier following RFC-616 output shape:

```python
class ReportScenarioClassification(BaseModel):
    scenario: str
    sections: list[str]
    contextual_focus: list[str]
    evidence_emphasis: str
```

**Input**: research topic, effort, loop count, source/URL counts, condensed snippet summaries.  
**Model**: `fast` role.

**Built-in scenarios (phase 1)**:

| Scenario | Typical topic |
|----------|---------------|
| `landscape_survey` | "state of X in 2026" |
| `how_to_guide` | "how to set up X" |
| `comparison` | "X vs Y" |
| `fact_check` | "is it true that…" |
| `general_research` | fallback |

### 6.2 Format consistency

Reuse presentation rules from `synthesis_report_system.xml` (GFM tables, bullets; IG-552) so CLI/TUI matches goal completion reports.

### 6.3 Mandatory Scope banner

Every report opens with:

> **Scope:** This report is based on public web sources only. Local repository files were not analyzed.

### 6.4 References

Append crawled URLs with titles and search-query provenance.

---

## 7. Plugin and integration

```python
@plugin(name="deep_research", version="1.0.0", trust_level="built-in")
class DeepResearchPlugin:
    @subagent(name="deep_research", triggers=["DEEP_RESEARCH_RULES", "context"])
    async def create_subagent(...):
        return create_deep_research_subagent(...)
```

| Surface | Value |
|---------|-------|
| Resolver factory key | `deep_research` |
| Discovery | `soothe.subagents.deep_research` |
| Config | `subagents.deep_research` in YAML |
| Slash | `/deep_research` |

**Subagent description (routing)**:

```
deep_research: Iterative public web research with URL crawling and adaptive report
generation. Use for external facts, comparisons, how-tos, and industry landscape.
Do NOT use for local codebase, repository files, or academic literature (use
academic_research when available).
```

**Removed (no aliases)**: All identifiers from the prior monolithic research subagent (config keys, slash routes, wire event namespaces, package path).

---

## 8. Wire events

| Event type | When | Key fields |
|------------|------|------------|
| `soothe.subagent.deep_research.started` | Research begins | `topic_preview`, `effort` |
| `soothe.subagent.deep_research.progress` | Phase complete | `phase`, `loop_count`, `message` |
| `soothe.subagent.deep_research.gather.summary` | Search done | `query_preview`, `result_count` |
| `soothe.subagent.deep_research.crawl.summary` | Crawl batch done | `urls_crawled`, `success_count` |
| `soothe.subagent.deep_research.completed` | Report done | `duration_ms`, `scenario`, `report_length` |

---

## 9. Error handling

| Failure | Behavior |
|---------|----------|
| Web search timeout / empty | Reflect retries with broadened query once; else report "limited public evidence" |
| Individual URL crawl failure | Skip URL; use search snippet if available |
| All crawls fail | Proceed with search snippets only |
| Report classifier timeout | Fall back to `general_research` scenario |
| Synthesize timeout | `general_research` template + raw evidence appendix |

---

## 10. Relationship to other agents

| Agent | Use when |
|-------|----------|
| **deep_research** | Public web facts, comparisons, how-tos, industry landscape |
| **academic_research** | Papers, literature review, citation-heavy research |
| **plan** | Structured planning and goal decomposition |
| **browser_use** | Interactive browser automation |
| **Main agent file tools** | Local codebase search, file reads, repo structure |

---

## 11. Phase 2 — `academic_research`

Separate package at `subagents/academic_research/`:

- Sources: academic search only (DeepXiv) + shared `url_crawl`
- Own `ReportScenarioClassifier` with academic scenarios (`literature_review`, `paper_comparison`, `method_survey`, `citation_analysis`, `general_academic`)
- Same engine *pattern* as `deep_research`, with separate events, config, plugin registration, and CLI slash `/academic_research`
- Effort levels: `normal` | `thorough`

---

## 12. Conclusion

RFC-619 defines **`deep_research`** (public web) and **`academic_research`** (academic literature): iterative research with crawl-on-discovery and adaptive reports. Both replace the prior multi-source Deep Research agent with a clean break. Local repository analysis remains on the main agent file tools.
