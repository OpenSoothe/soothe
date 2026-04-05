# IG-056: PaperScout Subagent as Community Plugin

**Status**: 🚧 In Progress
**Created**: 2026-03-25
**RFC**: RFC-600 (Plugin Extension System)

## Overview

Migrate PaperScout from Alithia to Soothe as the first community plugin, demonstrating RFC-600 plugin architecture and establishing patterns for future community contributions.

## Goals

1. Create `src/soothe_community/` package structure for community plugins
2. Migrate PaperScout subagent with full RFC-600 compliance
3. Use Soothe's `PersistStore` for storage instead of custom backend
4. Integrate configuration into Soothe's config system
5. Implement hybrid notification approach (email + events)
6. Achieve >80% test coverage
7. Pass all verification checks (formatting, linting, tests)

## Implementation Phases

### Phase 1: Project Structure ✅
- [x] Create `src/soothe_community/__init__.py`
- [x] Create `src/soothe_community/README.md`
- [x] Create `src/soothe_community/paperscout/` package structure

### Phase 2: Event System 🚧
- [ ] Create `events.py` with 4 event types
- [ ] Register events using `register_event()`
- [ ] Follow browser subagent pattern

### Phase 3: Data Models
- [ ] Port `models.py` (ArxivPaper, ZoteroPaper, ScoredPaper)
- [ ] Port `state.py` (PaperScoutConfig, AgentState)
- [ ] Use Pydantic v2 with `ConfigDict`

### Phase 4: Core Components
- [ ] Port `reranker.py` (paper ranking with sentence-transformers)
- [ ] Port `email.py` (HTML email formatting + SMTP)
- [ ] Port `gap_scanner.py` (missed notification detection)

### Phase 5: Workflow Implementation
- [ ] Port `nodes.py` (LangGraph workflow nodes)
- [ ] Migrate from custom storage to `PersistStore`
- [ ] Add event emission at key steps
- [ ] Replace noesium imports with langchain/stdlib

### Phase 6: Plugin Registration
- [ ] Create `implementation.py` (subagent factory)
- [ ] Create `__init__.py` with `@plugin` and `@subagent` decorators
- [ ] Implement `on_load()` lifecycle hook
- [ ] Implement dependency validation

### Phase 7: Configuration
- [ ] Update `pyproject.toml` with paperscout extras
- [ ] Document configuration structure in README
- [ ] Support environment variable injection

### Phase 8: Testing
- [ ] Create test suite in `tests/unit/community/test_paperscout/`
- [ ] Mock external APIs (ArXiv, Zotero, PapersWithCode, SMTP)
- [ ] Test event registration and emission
- [ ] Test plugin lifecycle (load/unload)
- [ ] Test workflow execution

### Phase 9: Verification
- [ ] Run `./scripts/verify_finally.sh`
- [ ] All 900+ existing tests pass
- [ ] New tests achieve >80% coverage
- [ ] Zero linting errors
- [ ] Formatting passes

## Key Architectural Decisions

### Decision 1: Storage Backend
**Chosen**: Use Soothe's `PersistStore` instead of custom `StorageBackend`

**Rationale**:
- Consistency with Soothe architecture
- Leverage durability features
- Less code to maintain
- Multiple backend options (Json, RocksDB, PostgreSQL)

**Implementation**:
```python
# Old: custom StorageBackend with ~25 methods
storage.cache_zotero_papers(user_id, papers)

# New: PersistStore API
store.set(f"paperscout:zotero:{user_id}", papers)
```

### Decision 2: Configuration Integration
**Chosen**: Integrate into Soothe's `config.yml`

**Rationale**:
- Follows existing patterns (e.g., browser subagent)
- Single source of truth for configuration
- Environment variable injection support
- Type-safe with Pydantic models

**Structure**:
```yaml
subagents:
  paperscout:
    enabled: true
    model: "openai:gpt-4o-mini"
    config:
      arxiv_categories: [cs.AI, cs.CV, cs.LG]
      max_papers: 25
      smtp:
        host: "${SMTP_HOST}"
        user: "${SMTP_USER}"
        password: "${SMTP_PASSWORD}"
```

### Decision 3: Notifications
**Chosen**: Hybrid approach (email + events)

**Rationale**:
- Email is PaperScout's core purpose
- Events enable observability and alternative channels
- Future-proof for Slack/Discord integrations
- No behavior change from original implementation

**Implementation**:
```python
# Send email (primary)
send_email(recipient, papers)

# Emit event (observability)
emit_event("soothe.community.paperscout.email_sent", {
    "recipient": recipient,
    "papers_count": len(papers)
})
```

## Migration Details

### Dependencies

**From Alithia**:
- `noesium.core.llm` → `langchain` models
- `noesium.core.utils` → Python `logging`
- `alithia.storage.base` → `soothe.backends.persistence`
- `alithia.researcher.profile` → Soothe config

**Keep**:
- `arxiv>=2.0.0` - ArXiv API client
- `sentence-transformers>=2.2.0` - Paper embeddings
- `pyzotero>=1.5.0` - Zotero API
- `tiktoken` - Token counting
- `feedparser` - RSS parsing
- `sklearn` - Cosine similarity

### File Mapping

| Original (Alithia) | New (Soothe) | Changes |
|-------------------|--------------|---------|
| `alithia/paperscout/agent.py` | `paperscout/implementation.py` | Simplified to factory |
| `alithia/paperscout/state.py` | `paperscout/state.py` | Pydantic v2 models |
| `alithia/paperscout/nodes.py` | `paperscout/nodes.py` | PersistStore + events |
| `alithia/paperscout/reranker.py` | `paperscout/reranker.py` | Minimal changes |
| `alithia/paperscout/email.py` | `paperscout/email.py` | Add event emission |
| `alithia/paperscout/models.py` | `paperscout/models.py` | Pydantic v2 |
| `alithia/paperscout/gap_scanner.py` | `paperscout/gap_scanner.py` | Minimal changes |
| N/A | `paperscout/events.py` | NEW: Event definitions |
| N/A | `paperscout/__init__.py` | NEW: Plugin registration |

### Storage Migration

**Key mapping**:
```python
# Zotero cache
"paperscout:zotero:{user_id}" → List[ZoteroPaper]

# Emailed papers (30-day lookback)
"paperscout:emailed:{user_id}" → Set[str]  # arxiv_ids

# Processed date ranges
"paperscout:ranges:{user_id}" → List[DateRange]

# Notification records
"paperscout:notifications:{user_id}:{date}" → NotificationRecord

# Assessed papers cache
"paperscout:assessed:{user_id}" → Dict[str, float]  # arxiv_id → score
```

## Testing Strategy

### Test Categories

1. **Event Tests** (`test_events.py`)
   - Event registration succeeds
   - Event classes have correct types
   - Summary templates work

2. **Plugin Tests** (`test_plugin.py`)
   - Plugin loads successfully
   - Dependencies validated
   - Lifecycle hooks work
   - Subagent creation works

3. **Node Tests** (`test_nodes.py`)
   - Each node executes correctly
   - PersistStore integration works
   - Events emitted at right times
   - Error handling works

4. **Reranker Tests** (`test_reranker.py`)
   - Sentence transformer initialization
   - Paper ranking produces scores
   - Time-decay weighting works
   - Fallback on errors

5. **Integration Tests** (`conftest.py`)
   - Mock ArXiv API responses
   - Mock Zotero API responses
   - Mock SMTP sending
   - Mock PapersWithCode API

### Mocking Strategy

```python
# conftest.py
@pytest.fixture
def mock_arxiv():
    """Mock ArXiv API responses."""
    with patch("arxiv.Search") as mock:
        mock.return_value.results.return_value = [
            # Mock paper objects
        ]
        yield mock

@pytest.fixture
def mock_zotero():
    """Mock Zotero API responses."""
    with patch("pyzotero.Zotero") as mock:
        mock.return_value.everything.return_value = [
            # Mock Zotero items
        ]
        yield mock

@pytest.fixture
def mock_persist_store():
    """Mock PersistStore for testing."""
    store = MagicMock(spec=PersistStore)
    store.get.return_value = None
    store.set.return_value = None
    return store
```

## Issues and Solutions

### Issue 1: Storage Backend Complexity
**Problem**: Custom StorageBackend has ~25 methods, complex migration
**Solution**: Start with simple PersistStore key-value mapping, iterate

### Issue 2: External API Rate Limits
**Problem**: ArXiv/Zotero APIs have rate limits
**Solution**: Mock all APIs in tests, add rate limiting in production code

### Issue 3: Large Dependency Footprint
**Problem**: Heavy dependencies (sentence-transformers, etc.)
**Solution**: Make paperscout an optional extra: `pip install soothe[paperscout]`

### Issue 4: Email Deliverability
**Problem**: SMTP providers may block emails
**Solution**: Test with multiple providers, add SMTP debugging, document common issues

## Verification Checklist

- [ ] `./scripts/verify_finally.sh` passes
- [ ] All 900+ existing tests pass
- [ ] New PaperScout tests pass
- [ ] Test coverage > 80%
- [ ] `make lint` - zero errors
- [ ] `make format-check` - passes
- [ ] `soothe checkhealth` - plugin loads successfully
- [ ] Manual test with real Zotero account works
- [ ] Manual test with real SMTP works

## Lessons Learned

*(To be filled during implementation)*

## References

- [RFC-600: Plugin Extension System](../specs/RFC-600-plugin-extension-system.md)
- [IG-052: Event System Optimization](IG-052.md)
- [Browser Subagent Implementation](../../src/soothe/subagents/browser/)
- [Original PaperScout](../../thirdparty/Alithia/alithia/paperscout/)
- [Soothe Development Guide](../CLAUDE.md)
