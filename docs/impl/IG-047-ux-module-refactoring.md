# IG-047: UX Module Refactoring

**Status**: Draft
**Created**: 2026-03-22
**RFC References**: None (internal refactoring)
**Related Guides**: IG-034 (CLI Modularization), IG-041 (CLI Polish)

## Objective

Refactor the `soothe.ux` package into a new `soothe.ux` package structure with clear separation of concerns:
- **`soothe.ux.cli`** - CLI-based UX implementation (argument parsing, commands, headless execution)
- **`soothe.ux.tui`** - TUI-based UX implementation (Textual app, widgets, interactive rendering)
- **`soothe.ux.shared`** - Common utilities between both modes (message processing, event filtering, slash commands)
- **`soothe.ux.core`** - UX infrastructure (config loading, logging setup, migrations)

## Motivation

The current `soothe.ux` package mixes:
1. CLI-specific code (argument parsing, command implementations)
2. TUI-specific code (Textual widgets, screens)
3. Shared utilities (message processing, event filtering)
4. Infrastructure (config loading, logging)

This violates the single responsibility principle and makes the architecture harder to understand and maintain.

## Design

### Package Structure

```
src/soothe/ux/
├── __init__.py                      # Re-export key public APIs
├── cli/                             # CLI-based UX implementation
│   ├── __init__.py
│   ├── main.py                      # Typer app entry point
│   ├── commands/                    # All CLI commands
│   │   ├── __init__.py
│   │   ├── auth_cmd.py
│   │   ├── autopilot_cmd.py
│   │   ├── config_cmd.py
│   │   ├── run_cmd.py
│   │   ├── server_cmd.py
│   │   ├── status_cmd.py
│   │   ├── thread_cmd.py
│   │   └── subagent_names.py
│   ├── execution/                   # Execution modes
│   │   ├── __init__.py
│   │   ├── daemon_runner.py
│   │   ├── headless.py
│   │   ├── standalone_runner.py
│   │   └── tui.py
│   └── rendering/                   # CLI-specific rendering
│       ├── __init__.py
│       ├── cli_event_renderer.py
│       └── progress_renderer.py
├── tui/                             # TUI-based UX implementation
│   ├── __init__.py
│   ├── app.py
│   ├── widgets.py
│   ├── state.py
│   ├── renderers.py
│   ├── event_processors.py
│   └── tui_event_renderer.py
├── shared/                          # Shared utilities
│   ├── __init__.py
│   ├── message_processing.py
│   ├── progress_verbosity.py
│   ├── rendering.py                 # Renamed from tui_shared.py
│   └── slash_commands.py
└── core/                            # UX infrastructure
    ├── __init__.py
    ├── config_loader.py
    ├── logging_setup.py
    └── migrations.py
```

### Module Migration Mapping

| Source | Destination | Notes |
|--------|-------------|-------|
| `cli/main.py` | `ux/cli/main.py` | Entry point |
| `cli/commands/*` (10 files) | `ux/cli/commands/*` | Command implementations |
| `cli/execution/daemon_runner.py` | `ux/cli/execution/` | |
| `cli/execution/headless.py` | `ux/cli/execution/` | |
| `cli/execution/standalone_runner.py` | `ux/cli/execution/` | |
| `cli/execution/tui.py` | `ux/cli/execution/` | TUI launcher |
| `cli/execution/postgres_check.py` | `utils/postgres.py` | Move to utils |
| `cli/rendering/*` (2 files) | `ux/cli/rendering/*` | |
| `cli/tui/*` (6 files) | `ux/tui/*` | |
| `cli/message_processing.py` | `ux/shared/` | |
| `cli/progress_verbosity.py` | `ux/shared/` | |
| `cli/tui_shared.py` | `ux/shared/rendering.py` | Rename |
| `cli/slash_commands.py` | `ux/shared/` | |
| `cli/core/*` (3 files) | `ux/core/*` | |

## Implementation Steps

### Step 1: Create Package Structure (30 min)

```bash
# Create directories
mkdir -p src/soothe/ux/{cli/{commands,execution,rendering},tui,shared,core}

# Create __init__.py files
touch src/soothe/ux/__init__.py
touch src/soothe/ux/cli/__init__.py
touch src/soothe/ux/cli/commands/__init__.py
touch src/soothe/ux/cli/execution/__init__.py
touch src/soothe/ux/cli/rendering/__init__.py
touch src/soothe/ux/tui/__init__.py
touch src/soothe/ux/shared/__init__.py
touch src/soothe/ux/core/__init__.py
```

### Step 2: Move postgres_check.py (15 min)

```bash
# Create utils module if needed
mkdir -p src/soothe/utils

# Move and rename
git mv src/soothe/cli/execution/postgres_check.py src/soothe/utils/postgres.py
```

Update imports:
- `soothe/core/resolver/_resolver_infra.py`
- `soothe/cli/execution/__init__.py`

### Step 3: Migrate Shared Modules (45 min)

**Priority order to avoid circular imports:**

1. **ux.shared** (no internal dependencies):
```bash
git mv src/soothe/cli/message_processing.py src/soothe/ux/shared/
git mv src/soothe/cli/progress_verbosity.py src/soothe/ux/shared/
git mv src/soothe/cli/tui_shared.py src/soothe/ux/shared/rendering.py
git mv src/soothe/cli/slash_commands.py src/soothe/ux/shared/
```

2. Update imports in migrated files:
   - `ux/shared/message_processing.py`: Update `from soothe.ux.shared.progress_verbosity` → `from soothe.ux.shared.progress_verbosity`
   - `ux/shared/message_processing.py`: Update `from soothe.ux.shared.rendering` → `from soothe.ux.shared.rendering`

### Step 4: Migrate Core Modules (30 min)

```bash
git mv src/soothe/cli/core/config_loader.py src/soothe/ux/core/
git mv src/soothe/cli/core/logging_setup.py src/soothe/ux/core/
git mv src/soothe/cli/core/migrations.py src/soothe/ux/core/
```

Update imports as needed.

### Step 5: Migrate CLI Rendering (20 min)

```bash
git mv src/soothe/cli/rendering/cli_event_renderer.py src/soothe/ux/cli/rendering/
git mv src/soothe/cli/rendering/progress_renderer.py src/soothe/ux/cli/rendering/
```

Update imports:
- Change `from soothe.ux.shared.progress_verbosity` → `from soothe.ux.shared.progress_verbosity`
- Change `from soothe.ux.shared.message_processing` → `from soothe.ux.shared.message_processing`

### Step 6: Migrate CLI Commands (1 hour)

```bash
git mv src/soothe/cli/commands/*.py src/soothe/ux/cli/commands/
```

Update imports in each file:
- `from soothe.ux.core` → `from soothe.ux.core`
- `from soothe.ux.execution` → `from soothe.ux.cli.execution`
- `from soothe.ux.commands` → `from soothe.ux.cli.commands`

### Step 7: Migrate CLI Execution (45 min)

```bash
git mv src/soothe/cli/execution/daemon_runner.py src/soothe/ux/cli/execution/
git mv src/soothe/cli/execution/headless.py src/soothe/ux/cli/execution/
git mv src/soothe/cli/execution/standalone_runner.py src/soothe/ux/cli/execution/
git mv src/soothe/cli/execution/tui.py src/soothe/ux/cli/execution/
```

Update imports in each file.

### Step 8: Migrate CLI Main (30 min)

```bash
git mv src/soothe/cli/main.py src/soothe/ux/cli/main.py
```

Update all imports:
- `from soothe.ux.commands` → `from soothe.ux.cli.commands`
- `from soothe.ux.core` → `from soothe.ux.core`

### Step 9: Migrate TUI Modules (1 hour)

```bash
git mv src/soothe/cli/tui/*.py src/soothe/ux/tui/
```

Update imports:
- `from soothe.ux.shared.rendering` → `from soothe.ux.shared.rendering`
- `from soothe.ux.shared.message_processing` → `from soothe.ux.shared.message_processing`
- `from soothe.ux.shared.progress_verbosity` → `from soothe.ux.shared.progress_verbosity`
- `from soothe.ux.shared.slash_commands` → `from soothe.ux.shared.slash_commands`

### Step 10: Update External Imports (1.5 hours)

Update files outside `soothe.ux` that import from old paths:

**soothe.daemon**:
- `daemon/_handlers.py`: `from soothe.ux.shared.slash_commands` → `from soothe.ux.shared.slash_commands`
- `daemon/entrypoint.py`: `from soothe.ux.core.logging_setup` → `from soothe.ux.core.logging_setup`
- `daemon/thread_logger.py`: `from soothe.ux.shared.message_processing` → `from soothe.ux.shared.message_processing`

**soothe.core**:
- `core/event_catalog.py`: `from soothe.ux.shared.progress_verbosity` → `from soothe.ux.shared.progress_verbosity`
- `core/resolver/_resolver_infra.py`: `from soothe.ux.cli.execution.postgres_check` → `from soothe.utils.postgres`

### Step 11: Update pyproject.toml (5 min)

```toml
# Change entry point
[project.scripts]
soothe = "soothe.ux.cli.main:app"
```

Also update if there's a `__main__.py` reference.

### Step 12: Update Tests (2 hours)

Update all test imports (32 files):

```bash
# Find all test files with old imports
grep -r "from soothe.ux" tests/ | cut -d: -f1 | sort -u

# Update each file
# Use find-and-replace or manual editing
```

Priority order:
1. `tests/unit_tests/test_message_processing.py`
2. `tests/unit_tests/test_progress_verbosity.py`
3. `tests/unit_tests/test_cli_*.py` (8 files)
4. `tests/unit_tests/test_cli_tui_*.py`
5. `tests/integration_tests/`

### Step 13: Update Documentation (1.5 hours)

Update documentation files (16 files):

1. **CLAUDE.md**:
   - Update architecture diagram
   - Update module map table
   - Update all import examples

2. **Implementation guides** in `docs/impl/`:
   - `034-cli-modularization.md`
   - `041-cli-polish.md`
   - `042-tool-events-polish.md`
   - `046-unified-daemon-protocol.md`
   - Others with `soothe.ux` references

3. **src/soothe/cli/README.md** → Move to `src/soothe/ux/README.md`

Use grep to find all references:
```bash
grep -r "soothe\.cli" docs/
grep -r "from soothe.ux" docs/
```

### Step 14: Delete Old Package (10 min)

```bash
# Remove old cli package
rm -rf src/soothe/cli/
```

### Step 15: Verification (30 min)

```bash
# Run linting
make lint

# Run all tests
pytest tests/

# Test CLI commands
soothe --help
soothe --version
soothe run --help

# Test TUI (manual)
soothe run

# Test headless
soothe run "test prompt"

# Test daemon
soothe daemon start
soothe daemon status
soothe daemon stop
```

### Step 16: Update CHANGELOG (15 min)

Add breaking change notice:

```markdown
## [Unreleased]

### Breaking Changes

- **Module reorganization**: All `soothe.ux` modules moved to `soothe.ux`
  - `soothe.ux.main` → `soothe.ux.cli.main`
  - `soothe.ux.cli.commands.*` → `soothe.ux.cli.commands.*`
  - `soothe.ux.tui.*` → `soothe.ux.tui.*`
  - `soothe.ux.shared.message_processing` → `soothe.ux.shared.message_processing`
  - `soothe.ux.shared.progress_verbosity` → `soothe.ux.shared.progress_verbosity`
  - `soothe.ux.shared.slash_commands` → `soothe.ux.shared.slash_commands`
  - `soothe.ux.core.*` → `soothe.ux.core.*`

  If you have code that imports from `soothe.ux`, update your imports to use `soothe.ux` paths.

### Changed

- Improved module organization with clear separation between CLI, TUI, and shared utilities
- Moved database utilities from `soothe.ux.cli.execution.postgres_check` to `soothe.utils.postgres`
```

## Total Time Estimate

- Setup and migration: 6-7 hours
- Testing and verification: 1 hour
- Documentation: 1.5 hours
- **Total**: 8.5-9.5 hours

## Critical Files

### Top 10 Files Requiring Careful Review

1. `src/soothe/ux/cli/main.py` - Entry point, many imports
2. `src/soothe/ux/shared/message_processing.py` - Shared core, used everywhere
3. `src/soothe/ux/shared/slash_commands.py` - Used by TUI and daemon
4. `src/soothe/ux/tui/app.py` - Main TUI app
5. `src/soothe/ux/cli/commands/run_cmd.py` - Main run logic
6. `src/soothe/ux/cli/execution/headless.py` - Headless execution
7. `src/soothe/ux/cli/execution/daemon_runner.py` - Daemon client
8. `src/soothe/ux/shared/rendering.py` - Plan rendering utilities
9. `src/soothe/ux/core/config_loader.py` - Config loading
10. `src/soothe/utils/postgres.py` - Moved database utility

## Testing Strategy

### Unit Tests

- All existing unit tests should pass after import updates
- Focus on test files that mock or patch `soothe.ux.*` paths

### Integration Tests

- `test_cli_daemon.py` - Daemon communication
- `test_cli_session.py` - Session management
- `test_tool_integration_real_llm.py` - End-to-end

### Manual Tests

1. CLI help and version
2. TUI launch and basic interaction
3. Headless single-prompt mode
4. Daemon start/stop/status
5. Thread operations
6. Config commands

## Risks

### Risk 1: Circular Imports
**Likelihood**: Low
**Impact**: High
**Mitigation**: Follow migration order strictly, test imports early

### Risk 2: Breaking External Users
**Likelihood**: Medium
**Impact**: Medium
**Mitigation**: Clear CHANGELOG notice, this is internal tool

### Risk 3: Test Breakage
**Likelihood**: Medium
**Impact**: Medium
**Mitigation**: Run tests after each step, fix immediately

### Risk 4: Documentation Drift
**Likelihood**: Low
**Impact**: Low
**Mitigation**: Update all docs in same PR

## Success Criteria

- [ ] All modules moved to `soothe.ux` package structure
- [ ] All imports updated to use new paths
- [ ] Old `soothe.ux` package deleted
- [ ] All tests pass
- [ ] `make lint` passes
- [ ] All CLI commands work
- [ ] TUI launches successfully
- [ ] Headless mode works
- [ ] Documentation updated
- [ ] CHANGELOG updated

## Post-Implementation

After merging:
1. Update any external tools/scripts that import from `soothe.ux`
2. Monitor for any issues in production usage
3. Consider adding module architecture diagram to docs