# IG-490: StrangeLoop Terminology Final Cleanup

## Summary
Complete the AgentLoop → StrangeLoop migration by cleansing remaining terminology
in RFC filenames, IG filenames, config fields, code references, and docs.

## Background
IG-488 renamed the core class from `AgentLoop` to `StrangeLoop` (alias `Sloop`).
This IG finishes the cleanup by renaming all remaining references.

## Categories of Changes

### 1. RFC Filename Renames (8 files)
Rename RFC files from `RFC-XXX-agentloop-*.md` to `RFC-XXX-strangeloop-*.md`:

| Old Filename | New Filename |
|--------------|--------------|
| `RFC-201-strangeloop-plan-execute-loop.md` | `RFC-201-strangeloop-plan-execute-loop.md` |
| `RFC-203-strangeloop-state-memory.md` | `RFC-203-strangeloop-state-memory.md` |
| `RFC-207-strangeloop-thread-context-lifecycle.md` | `RFC-207-strangeloop-thread-context-lifecycle.md` |
| `RFC-213-strangeloop-reasoning-quality.md` | `RFC-213-strangeloop-reasoning-quality.md` |
| `RFC-214-strangeloop-loop-message-surface.md` | `RFC-214-strangeloop-loop-message-surface.md` |
| `RFC-215-strangeloop-persistence-backend.md` | `RFC-215-strangeloop-persistence-backend.md` |
| `RFC-216-strangeloop-multithread-lifecycle.md` | `RFC-216-strangeloop-multithread-lifecycle.md` |
| `RFC-218-strangeloop-checkpoint-tree-architecture.md` | `RFC-218-strangeloop-checkpoint-tree-architecture.md` |

### 2. IG Filename Renames (1 file)
| Old Filename | New Filename |
|--------------|--------------|
| `IG-479-strangeloop-ledger-and-tui-subgraph-tool-fixes.md` | `IG-479-strangeloop-ledger-and-tui-subgraph-tool-fixes.md` |

### 3. Config Field Renames
Rename `agentloop_pool_size` → `sloop_pool_size`:
- `config/config.template.yml`
- `config/config.dev.yml`
- `config/config.integration-explore.yml`
- `packages/soothe/src/soothe/config/models.py`
- `packages/soothe-daemon/src/soothe_daemon/config/models.py`
- `packages/soothe-daemon/src/soothe_daemon/persistence/pool_sizing.py`
- `packages/soothe-daemon/src/soothe_daemon/persistence/__init__.py`
- All references in tests and docs

### 4. Database Table Names (Schema Change)
Rename tables in SQLite/Postgres schema:
- `agentloop_loops` → `sloop_loops`
- `agentloop_checkpoints` → `sloop_checkpoints`

Files affected:
- `packages/soothe/src/soothe/foundation/loop/state/persistence/sqlite_backend.py`
- `packages/soothe/src/soothe/foundation/loop/state/persistence/postgres_backend.py`
- `packages/soothe/src/soothe/foundation/loop/state/persistence/postgres_schema.py`
- Migration scripts in `packages/soothe/src/soothe/core/persistence/migrations/`

### 5. Function/API Renames
- `recommended_agentloop_pool_size` → `recommended_sloop_pool_size`
- `initialize_agentloop_postgres_schema` → `initialize_sloop_postgres_schema`
- `AGENTLOOP_POSTGRES_DATABASE` → `SLOOP_POSTGRES_DATABASE`
- `load_agentloop_checkpoint` → `load_sloop_checkpoint` (in docs only, already renamed in code)

### 6. Code Variable/Parameter Names
- `_agentloop_shared_pool` → `_sloop_shared_pool`
- `get_agentloop_shared_pool` → `get_sloop_shared_pool`
- `agentloop_result` → `sloop_result` (in planner.reflect)

### 7. Doc Content Updates
Update all doc references from AgentLoop to StrangeLoop:
- `docs/user_guide.md` - link texts
- `docs/specs/rfc-index.md` - index entries
- `docs/wiki/**/*.md` - all wiki pages
- Internal cross-references in all RFCs

### 8. Test Function Names
Rename test functions:
- `test_agentloop_*` → `test_strangeloop_*` or `test_sloop_*`

## Implementation Order
1. Rename RFC/IG files (git mv)
2. Update cross-references in all docs
3. Rename config fields
4. Rename database table names in schema
5. Rename function/API names
6. Rename code variables
7. Rename test functions
8. Run `./scripts/verify_finally.sh`

## Verification
- All lint checks pass
- All tests pass
- grep for `agentloop|agenticloop` returns only IG-488 migration docs