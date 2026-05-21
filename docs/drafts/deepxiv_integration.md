# Code Architecture Design: DeepXiv SDK Integration into Soothe

## Repository Overview

### DeepXiv SDK (External)

**Source**: https://github.com/DeepXiv/deepxiv_sdk

**Purpose**: Python client library providing progressive paper reading capabilities for academic papers from arXiv, bioRxiv, medRxiv, and PubMed Central with AI-generated TLDRs and section-level access.

**Key Capabilities**:
- Semantic paper search across multiple academic repositories
- Progressive content loading (brief → metadata → sections → full)
- AI-generated TLDR summaries and section overviews
- Trending paper discovery based on social signals
- Token-based access control with free tier (1,000 req/day auto-register) and registered tier (10,000 req/day)

**Dependencies**: `requests` for HTTP communication

---

### Soothe Framework (Target)

**Architecture**: Goal-driven orchestration framework for 24/7 autonomous agents built on deepagents and langchain ecosystem.

**Relevant Components for Tool Integration**:
- `packages/soothe/src/soothe/toolkits/` - Toolkit implementations following Pattern 2 (Toolkit + BaseTool)
- `packages/soothe/src/soothe/core/resolver/_resolver_tools.py` - Tool dispatch and initialization
- `soothe_sdk.plugin` - Plugin decorator system (`@plugin`, `@tool`, `@subagent`)
- `config/config.template.yml` and `config/config.dev.yml` - Configuration schema
- `docs/specs/RFC-600-plugin-extension-system.md` - Plugin extension architecture

---

## SDK Structure Analysis

### Core Module: `deepxiv_sdk.reader.Reader`

**Main Entry Point**: `Reader` class provides all SDK functionality through lazy-loaded endpoints.

**Constructor Parameters**:
```python
Reader(
    token: str | None = None,      # API token (optional, auto-registers if None)
    base_url: str = "https://data.rag.ac.cn",
    timeout: int = 60,
    max_retries: int = 3,
)
```

**Key Methods**:

| Method | Parameters | Returns | Purpose |
|--------|------------|---------|---------|
| `search()` | query, size, source, categories, authors, organizations, date_from, date_to, min_citation | Dict with `result` list and `total_count` | Semantic paper search |
| `brief()` | arxiv_id | Dict with title, TLDR, keywords, citations, github_url | Quick paper summary |
| `head()` | arxiv_id | Dict with title, authors, abstract, sections (with token counts) | Paper metadata and structure |
| `section()` | arxiv_id, section_name | str | Section content (markdown) |
| `raw()` | arxiv_id | str | Full paper content (markdown) |
| `trending()` | days, limit | Dict with papers list | Trending papers by social signals |
| `websearch()` | query | Dict | Web search (costs 20 tokens vs 1 for paper search) |
| `pmc_head()` | pmc_id | Dict | PMC paper metadata |
| `pmc_section()` | pmc_id, section_name | str | PMC section content |

**Exception Hierarchy**:
```
deepxiv_sdk.exceptions.APIError (base)
├── AuthenticationError
├── RateLimitError
├── NotFoundError
└── BadRequestError
```

### Response Patterns

**Search Results**:
```python
{
    "result": [
        {
            "arxiv_id": "2409.05591",  # or biorxiv_id, medrxiv_id
            "title": "...",
            "abstract": "...",
            "score": 0.89,
            "citation_count": 42,
            "publish_at": "2024-09-09",
            "authors": [{"name": "..."}],
            "categories": ["cs.AI", "cs.CL"],
        }
    ],
    "total_count": 156
}
```

**Brief Response**:
```python
{
    "title": "...",
    "tldr": "AI-generated summary...",
    "keywords": ["keyword1", "keyword2"],
    "citations": 42,
    "publish_at": "2024-09-09",
    "pdf_url": "https://arxiv.org/pdf/...",
    "github_url": "https://github.com/...",  # if available
}
```

**Head Response**:
```python
{
    "title": "...",
    "authors": [{"name": "..."}],
    "abstract": "...",
    "categories": [...],
    "publish_at": "...",
    "token_count": 45000,
    "sections": {
        "Introduction": {"token_count": 2000, "tldr": "..."},
        "Method": {"token_count": 5000, "tldr": "..."},
        ...
    }
}
```

---

## Integration Patterns

### Soothe Tool Architecture Patterns

**Pattern 1: Simple Function Tool**
- Single `@tool` decorated function
- No state management
- Example: Built-in tools in `tools/` directory

**Pattern 2: Toolkit + BaseTool Subclasses** (Recommended for DeepXiv)
- Toolkit class manages shared state (Reader instance, configuration)
- Multiple `BaseTool` subclasses for different operations
- Each tool holds reference to shared toolkit
- Clean separation of concerns

**Pattern 3: Plugin with Lifecycle**
- `@plugin` decorated class with `on_load()`, `get_tools()` methods
- Integrates with Soothe's configuration system
- Supports dependency injection
- Best for external SDK integration

### Configuration Injection Pattern

**Environment Variable Fallback**:
```python
token = config.tools.deepxiv.token  # From YAML config (can use ${DEEPXIV_API_KEY})
   or os.environ.get("DEEPXIV_API_KEY")  # Direct env var
   or None  # Auto-register anonymous token
```

**Config Template Entry** (config/config.template.yml):
```yaml
tools:
  deepxiv:
    token: ${DEEPXIV_API_KEY:-}  # Support env var substitution
    timeout: 60
    max_retries: 3
```

### Lazy Initialization Pattern

The DeepXiv `Reader` should be lazily initialized to avoid API calls during tool loading:

```python
class DeepxivToolkit:
    def __init__(self, token: str | None, ...):
        self.token = token
        self._reader: Reader | None = None
    
    @property
    def reader(self) -> Reader:
        if self._reader is None:
            from deepxiv_sdk import Reader
            self._reader = Reader(token=self.token)
        return self._reader
```

### Error Handling Pattern

Convert SDK exceptions to user-friendly messages:

```python
from deepxiv_sdk import (
    APIError,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
)

def _safe_call(tool_func):
    @wraps(tool_func)
    def wrapper(*args, **kwargs):
        try:
            return tool_func(*args, **kwargs)
        except AuthenticationError:
            return "Error: Invalid DeepXiv token. Configure DEEPXIV_API_KEY or get one at data.rag.ac.cn"
        except RateLimitError:
            return "Error: Daily API limit reached. Register at data.rag.ac.cn for higher limits."
        except NotFoundError:
            return "Error: Paper not found. Check the ID and try again."
        except APIError as e:
            return f"Error: DeepXiv API error - {e}"
    return wrapper
```

---

## Tool Design Recommendations

### Recommended Tool Set (7 Tools)

| Tool | Purpose | Token Cost | Use Case |
|------|---------|------------|----------|
| `deepxiv_search` | Paper search | 1 token per request | Literature review, finding papers |
| `deepxiv_paper_brief` | Quick summary | 1 token per request | Relevance assessment |
| `deepxiv_paper_metadata` | Structure overview | 1 token per request | Navigation planning |
| `deepxiv_read_section` | Section content | 1 token per request | Targeted reading |
| `deepxiv_get_full_paper` | Complete paper | 1 token per request | Deep analysis (expensive) |
| `deepxiv_trending` | Hot papers | 1 token per request | Discovery, staying current |
| `deepxiv_websearch` | Web search | 20 tokens per request | Broader context |

### Progressive Reading Workflow

The tools support DeepXiv's progressive reading pattern optimized for token efficiency:

```
Search → Brief → Metadata → Section(s) → Full Paper
  ↓         ↓         ↓           ↓            ↓
Find    Quick     Understand   Read only    Complete
papers  assess    structure   what's       analysis
                           needed
```

**Agent Decision Tree**:
1. Use `deepxiv_search` to find candidate papers
2. Use `deepxiv_paper_brief` for quick relevance check (saves tokens vs reading abstract)
3. Use `deepxiv_paper_metadata` to see available sections
4. Use `deepxiv_read_section` to read only relevant sections
5. Use `deepxiv_get_full_paper` only when comprehensive analysis is needed

### Tool Descriptions (Optimized for Agent Understanding)

Each tool's `description` field should be optimized for LLM understanding:

```python
# Good: Clear, actionable, includes cost/benefit tradeoff
description = (
    "Get a quick summary of an arXiv paper. "
    "Returns: title, AI-generated TLDR, keywords, citation count, GitHub link. "
    "Use this FIRST to decide if a paper is worth deeper reading. "
    "Cost: 1 API token. "
    "Parameters: arxiv_id (required) - e.g., '2409.05591'."
)

# Avoid: Vague, doesn't guide usage
description = "Get paper information."
```

### Resolver Dispatch Pattern

In `_resolver_tools.py`, add dispatch case:

```python
if name == "deepxiv":
    from soothe.toolkits.deepxiv import DeepxivPlugin
    
    plugin = DeepxivPlugin()
    await plugin.on_load(context)  # Pass context with config
    return plugin.get_tools()
```

---

## Implementation Roadmap

### Phase 1: Core Implementation

**File**: `packages/soothe/src/soothe/toolkits/deepxiv.py`

**Tasks**:
1. Create input schemas (Pydantic `BaseModel` for each tool)
2. Implement 7 tool classes extending `BaseTool`
3. Create `DeepxivToolkit` class with lazy Reader initialization
4. Create `DeepxivPlugin` class with `@plugin` decorator
5. Add comprehensive error handling
6. Add docstrings following Google style

**Estimated Lines**: ~400-500 lines

### Phase 2: Integration

**Files**:
- `packages/soothe/src/soothe/core/resolver/_resolver_tools.py`
- `config/config.template.yml`
- `config/config.dev.yml`
- `packages/soothe/pyproject.toml` (add dependency)

**Tasks**:
1. Add dispatch case in `_resolver_tools.py`
2. Add config schema to template and dev config
3. Add `deepxiv-sdk>=0.2.5` to dependencies
4. Export toolkit from `soothe.toolkits.__init__.py`

### Phase 3: Testing

**File**: `packages/soothe/tests/unit/toolkits/test_deepxiv.py`

**Test Cases**:
- Tool initialization with and without token
- Search with various filters
- Brief/metadata/section/raw operations
- Error handling (auth, rate limit, not found)
- Configuration injection
- Lazy reader initialization

### Phase 4: Documentation

**Files**:
- `docs/user_guide.md` (update with DeepXiv usage)
- `CHANGELOG.md` (add entry)
- Toolkit docstrings (complete API reference)

### Verification Checklist

Before commit, run:
```bash
./scripts/verify_finally.sh
```

This ensures:
- Code formatting (Ruff)
- Linting (zero errors)
- Unit tests (900+ tests pass)

### Dependencies to Add

In `packages/soothe/pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "deepxiv-sdk>=0.2.5",
]
```

### Configuration Schema (Complete)

**config/config.template.yml**:
```yaml
tools:
  # DeepXiv: Academic paper search and progressive reading
  # Get a token at https://data.rag.ac.cn/register (10,000 requests/day)
  # If not provided, auto-registers anonymous token (1,000 requests/day)
  deepxiv:
    token: ${DEEPXIV_API_KEY:-}
    timeout: 60
    max_retries: 3
```

**config/config.dev.yml**:
```yaml
tools:
  deepxiv:
    token: ${DEEPXIV_API_KEY:-}
    timeout: 60
    max_retries: 3
```

---

## Key Design Decisions

1. **Pattern Selection**: Use Pattern 2 (Toolkit + BaseTool) because DeepXiv has multiple related operations sharing configuration and Reader state.

2. **Lazy Initialization**: Defer Reader creation until first use to avoid API calls during tool loading.

3. **Progressive Reading Support**: Design tools to support the brief → metadata → section → full workflow, encouraging token-efficient agent behavior.

4. **Error Messages**: Provide actionable error messages that guide users to solutions (register for token, check paper ID).

5. **Configuration Fallback**: Support both YAML config (with env var substitution) and direct environment variables for flexibility.

6. **Plugin Architecture**: Use `@plugin` decorator to integrate with Soothe's lifecycle management and configuration injection.

7. **Minimal Dependencies**: Only require `deepxiv-sdk` (which itself only requires `requests`), keeping the dependency footprint small.

---

## Summary

The DeepXiv SDK integrates cleanly into Soothe's tool architecture using Pattern 2 (Toolkit + BaseTool subclasses) wrapped in a `@plugin` decorated class. The integration requires:

- **One new file**: `packages/soothe/src/soothe/toolkits/deepxiv.py` (~450 lines)
- **Three modifications**: resolver dispatch, config template, config dev
- **One dependency**: `deepxiv-sdk>=0.2.5`
- **Seven tools**: search, brief, metadata, section, full paper, trending, websearch

The design supports DeepXiv's progressive reading workflow, enabling Soothe agents to efficiently search, assess, and read academic papers while minimizing token usage through targeted section access.
