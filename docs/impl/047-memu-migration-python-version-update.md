# IG-047: memU Migration and Python Version Update

## Overview

Migrate Soothe's memU implementation from the `memu-py>=1.5.0` package wrapper to an internal file-based implementation from the noesium project. Update Python version support from 3.13+ to 3.10-3.14.

## Goals

1. **Remove external dependency** - Eliminate dependency on the `memu-py` package
2. **Broader Python support** - Support Python 3.10, 3.11, 3.12, 3.13, and 3.14
3. **File-based storage** - Simpler, more portable storage using markdown files
4. **Action-based architecture** - Modern function-calling design for LLM-driven memory operations
5. **Preserve API** - Keep `MemoryProtocol` interface unchanged for backward compatibility

## Background

### Current State
- memU implementation wraps `memu-py>=1.5.0` package
- Requires Python >=3.13 (due to memu-py constraint)
- Database-backed storage (PostgreSQL/SQLite/in-memory)
- 297-line adapter in `src/soothe/backends/memory/memu.py`

### Target State
- Internal memU implementation (~22 files, ~3,500 lines)
- Support Python >=3.10,<3.15
- File-based markdown storage in `~/.soothe/memory/`
- Function-calling architecture with LLM integration
- Two-layer adapter pattern preserving MemoryProtocol

## Implementation Steps

### Phase 1: Update Python Version Requirements (Day 1)

**Files:**
- `pyproject.toml` - Update `requires-python` and classifiers
- `.python-version` - Set default to 3.12
- `.github/workflows/ci.yml` - Test matrix: 3.10, 3.12, 3.14
- `.github/workflows/release.yml` - Build with 3.12

**Changes:**
```toml
requires-python = ">=3.10,<3.15"
```

**Verification:**
- CI runs on all three Python versions
- Package installs on Python 3.10+

### Phase 2: Copy memU Implementation (Day 1-2)

**Source:** `~/Workspace/noesium/noesium/src/noesium/core/memory/memu/`
**Destination:** `src/soothe/backends/memory/memu/`

**Copy 22 files:**
```
memu/
├── __init__.py
├── llm_adapter.py
├── memory_store.py
├── LICENSE.txt
├── config/
│   ├── __init__.py
│   ├── markdown_config.py
│   ├── memory_cat_config.yaml
│   └── prompts/
└── memory/
    ├── __init__.py
    ├── memory_agent.py
    ├── recall_agent.py
    ├── file_manager.py
    ├── embeddings.py
    └── actions/ (8 files)
```

**Command:**
```bash
cp -r ~/Workspace/noesium/noesium/src/noesium/core/memory/memu \
      src/soothe/backends/memory/
```

### Phase 3: Adapt Imports (Day 2)

Replace `noesium.*` imports with Soothe equivalents:

| Noesium Import | Soothe Equivalent |
|----------------|-------------------|
| `noesium.core.llm.BaseLLMClient` | Create `memu/llm_client.py` |
| `noesium.core.memory.models.*` | Create `memu/models.py` |
| `noesium.core.utils.logging.get_logger` | Use `logging.getLogger` |

**Files to update:**
1. `memory_store.py`
2. `llm_adapter.py`
3. `memory/memory_agent.py`
4. `memory/recall_agent.py`
5. `memory/file_manager.py`

### Phase 4: Create LLM Client Interface (Day 3)

**New file:** `src/soothe/backends/memory/memu/llm_client.py`

Define `BaseLLMClient` protocol with:
- `completion()` - Simple text completion
- `chat_completion()` - Completion with function calling
- `embed()` / `embed_batch()` - Embedding generation
- `get_embedding_dimensions()` - Vector size

**Classes:**
- `ChatCompletionResponse`
- `ToolCall`
- `FunctionCall`

### Phase 5: Create LangChain Adapter (Day 3)

**New file:** `src/soothe/backends/memory/memu/langchain_adapter.py`

`LangChainLLMAdapter` class:
- Wraps LangChain `BaseChatModel` and embedding model
- Converts between LangChain and BaseLLMClient interfaces
- Handles message conversion (dict → LangChain messages)
- Implements function calling via `bind_tools()`

### Phase 6: Create Memory Models (Day 4)

**New file:** `src/soothe/backends/memory/memu/models.py`

Models for internal use:
- `MemoryFilter` - Query filters
- `SearchResult` - Search with relevance score
- `MemoryStats` - Store statistics

### Phase 7: Create MemoryProtocol Adapter (Day 4-5)

**Rename:** `memu.py` → `memu_adapter.py`

`MemUMemory` class:
- Implements `MemoryProtocol`
- Wraps `MemuMemoryStore`
- Uses `LangChainLLMAdapter` for LLM integration
- Converts between Soothe and memU memory item formats

**Methods:**
- `remember()` → `store.add()`
- `recall()` → `store.search()`
- `recall_by_tags()` → `store.get_all(filters)`
- `forget()` → `store.delete()`
- `update()` → `store.update()`

### Phase 8: Update Configuration (Day 5)

**File:** `src/soothe/config/models.py`

Update `MemUConfig`:
```python
class MemUConfig(BaseModel):
    enabled: bool = True
    persist_dir: str | None = None  # NEW: file-based storage
    llm_chat_role: str = "fast"
    llm_embed_role: str = "embedding"
    enable_embeddings: bool = True
    enable_auto_categorization: bool = True
    enable_category_summaries: bool = True
    memory_categories: list[dict[str, str]] = [...]
```

Remove fields:
- `database_provider`
- `database_dsn`

**File:** `src/soothe/config/config.yml`

Update memory section with new fields.

### Phase 9: Update Resolver (Day 5)

**File:** `src/soothe/core/resolver/__init__.py`

Simplify `resolve_memory()`:
- Remove database config translation
- Create LangChain models directly
- Pass to `MemUMemory(config)`

### Phase 10: Update Exports (Day 5)

**File:** `src/soothe/backends/memory/__init__.py`

```python
from soothe.backends.memory.memu_adapter import MemUMemory
__all__ = ["MemUMemory"]
```

**File:** `src/soothe/backends/memory/memu/__init__.py`

Export key classes for advanced usage.

### Phase 11: Remove Old Implementation (Day 6)

**Delete:**
- Old `src/soothe/backends/memory/memu.py`

**Update:**
- Remove `memory` optional dependency from `pyproject.toml`
- Run `uv lock` to update lock file

### Phase 12: Update Tests (Day 6-7)

**File:** `tests/unit_tests/test_memory_memu.py`

Changes:
1. Remove `MemoryService` mocks
2. Mock `MemuMemoryStore` and file operations
3. Update initialization tests
4. Add adapter conversion tests
5. Add LangChain adapter tests

**Test categories:**
- Adapter tests (Soothe ↔ memU conversion)
- LLM adapter tests (LangChain ↔ BaseLLMClient)
- File-based storage tests
- Python version compatibility tests

### Phase 13: Update Documentation (Day 7)

**Files to update:**
- `docs/user_guide.md` - Update memory section
- `CLAUDE.md` - Update architecture section
- `README.md` - Update Python version badge

**Add migration guide:**
- `docs/migration/memu-file-migration.md`
- Script to migrate database → file storage

## Testing Plan

### Unit Tests
```bash
uv run pytest tests/unit_tests/test_memory_memu.py -v
```

### Integration Tests
```bash
uv run pytest tests/integration/ -k memory -v
```

### Python Version Matrix
```bash
# Test on all supported versions
for py in 3.10 3.12 3.14; do
    uv python install $py
    uv run pytest tests/unit_tests/test_memory_memu.py
done
```

### Manual Testing
```bash
# Test memory operations
soothe run "Remember that I prefer Python for data science"
soothe run "What programming preferences do I have?"

# Verify file storage
ls ~/.soothe/memory/default_agent/default_user/
```

## Success Criteria

- [ ] All existing tests pass
- [ ] `MemoryProtocol` interface unchanged
- [ ] Python 3.10, 3.12, 3.14 compatibility verified
- [ ] File-based storage working (`~/.soothe/memory/`)
- [ ] LLM integration functional
- [ ] No `memu-py` package dependency
- [ ] Documentation updated
- [ ] Migration guide provided

## Risks and Mitigations

### High Risk
1. **Data migration** - Existing users with database-backed memories
   - **Mitigation:** Provide migration script
   - **Mitigation:** Support both storage backends temporarily

2. **LLM adapter** - Function calling must work correctly
   - **Mitigation:** Comprehensive adapter tests
   - **Mitigation:** Test with multiple LangChain models

3. **Python 3.10 compatibility** - Type hints and syntax
   - **Mitigation:** Use `from __future__ import annotations`
   - **Mitigation:** Test on all versions

### Medium Risk
1. **File permissions** - Memory directory access
   - **Mitigation:** Graceful error messages
   - **Mitigation:** Default to user home directory

2. **Performance** - File-based vs database
   - **Mitigation:** Benchmark both approaches
   - **Mitigation:** Optimize file I/O

## Rollback Plan

If critical issues arise:

1. **Revert code changes:**
   ```bash
   git revert HEAD  # Revert migration commits
   ```

2. **Restore old files:**
   ```bash
   git checkout HEAD~N -- src/soothe/backends/memory/memu.py
   git checkout HEAD~N -- pyproject.toml
   ```

3. **Re-add dependency:**
   ```toml
   memory = ["memu-py>=1.5.0; python_version>='3.13'"]
   ```

4. **Restore Python requirement:**
   ```toml
   requires-python = ">=3.13,<4.0"
   ```

## Timeline

- **Day 1:** Python version updates + copy memU files
- **Day 2:** Import adaptations
- **Day 3:** LLM client interface + adapter
- **Day 4:** Memory models + MemoryProtocol adapter
- **Day 5:** Config + resolver + exports
- **Day 6:** Remove old implementation + tests
- **Day 7:** Documentation + final verification

## Dependencies

- No new external dependencies
- Uses existing LangChain integration
- File storage requires no additional packages

## References

- Plan file: `/Users/chenxm/.claude/plans/moonlit-beaming-zephyr.md`
- Source implementation: `~/Workspace/noesium/noesium/src/noesium/core/memory/memu/`
- RFC-0006: Context and Memory Architecture Design
- RFC-0008: Protocol Specification