# RFC: CLI Modularization Refactoring

**Status**: Approved
**Created**: 2026-03-18
**Author**: Claude Code

## Abstract

Refactor `src/soothe/cli/main.py` (1574 lines) into a modular architecture with clear separation of concerns. The monolithic main.py currently mixes utilities, execution logic, command handlers, and rendering, making it difficult to test, maintain, and extend.

## Motivation

### Current Problems

1. **Monolithic Structure**: Single 1574-line file with multiple responsibilities
2. **Poor Testability**: Hard to unit test individual components in isolation
3. **Tight Coupling**: Execution logic, commands, and utilities are intermingled
4. **Discoverability**: Related functionality scattered across the file
5. **Extensibility**: Adding new commands requires touching large file

### Goals

- Single Responsibility Principle: Each module has one clear purpose
- Clear dependency flow: main → commands → execution → core
- Improved testability through isolated modules
- Better code organization and discoverability
- No backwards compatibility constraints (cut change)

## Design

### Module Structure

```
src/soothe/cli/
├── main.py                         # Entry point & command registration (~150 lines)
├── commands.py                     # (existing) Slash commands for TUI
├── tui_app.py                      # (existing) TUI application
├── tui_shared.py                   # (existing) TUI shared utilities
├── daemon.py                       # (existing) Daemon management
├── thread_logger.py                # (existing) Thread logging
├── progress_verbosity.py           # (existing) Progress classification
│
├── core/                           # Core CLI utilities
│   ├── __init__.py                 # Exports: setup_logging, load_config, migrate_rocksdb
│   ├── logging_setup.py            # setup_logging() - 60 lines
│   ├── config_loader.py            # load_config(), config cache - 70 lines
│   └── migrations.py               # migrate_rocksdb_to_data_subfolder() - 50 lines
│
├── execution/                      # Execution modes
│   ├── __init__.py                 # Exports: run_tui, run_headless, run_headless_standalone
│   ├── tui.py                      # _run_tui() - 20 lines
│   ├── headless.py                 # run_headless() - 150 lines
│   ├── daemon_runner.py            # run_headless_via_daemon() - 210 lines
│   ├── standalone_runner.py        # run_headless_standalone() - 250 lines
│   └── postgres_check.py           # check_postgres_available() - 15 lines
│
├── commands/                       # CLI command groups
│   ├── __init__.py                 # Re-exports all commands
│   ├── run_cmd.py                  # run command - 90 lines
│   ├── config_cmd.py               # config command - 90 lines
│   ├── attach_cmd.py               # attach command - 45 lines
│   ├── init_cmd.py                 # init_soothe command - 55 lines
│   ├── server_cmd.py               # server start/stop/status - 80 lines
│   ├── thread_cmd.py               # thread list/resume/archive/inspect/delete/export - 260 lines
│   └── status_cmd.py               # list_subagents, list_subagents_status, show_config - 70 lines
│
└── rendering/                      # Output rendering
    ├── __init__.py                 # Exports: render_progress_event
    └── progress_renderer.py        # render_progress_event() - 150 lines
```

### Module Responsibilities

#### core/logging_setup.py
**Purpose**: Configure the soothe logger hierarchy

**Public API**:
```python
def setup_logging(config: SootheConfig | None = None) -> None:
    """Configure the soothe logger hierarchy with file and optional console handlers."""
```

**Dependencies**: `soothe.config`

#### core/config_loader.py
**Purpose**: Load and cache configuration

**Public API**:
```python
def load_config(config_path: str | None = None) -> SootheConfig:
    """Load configuration with caching."""
```

**Dependencies**: `soothe.config`

**Internal State**:
- `_DEFAULT_CONFIG_PATH`: Default config location
- `_config_cache`: Config cache dict

#### core/migrations.py
**Purpose**: One-time data migrations

**Public API**:
```python
def migrate_rocksdb_to_data_subfolder() -> None:
    """Migrate RocksDB data files to data/ subfolders."""
```

**Dependencies**: `soothe.config`

#### execution/tui.py
**Purpose**: Run TUI mode

**Public API**:
```python
def run_tui(cfg: SootheConfig, *, thread_id: str | None = None, config_path: str | None = None) -> None:
    """Launch the TUI application."""
```

**Dependencies**: `soothe.ux.tui_app`, `soothe.daemon`

#### execution/headless.py
**Purpose**: Orchestrate headless execution (daemon vs standalone)

**Public API**:
```python
def run_headless(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt with streaming output."""
```

**Dependencies**: `execution.daemon_runner`, `execution.standalone_runner`, `soothe.daemon`

#### execution/daemon_runner.py
**Purpose**: Execute via daemon client

**Public API**:
```python
async def run_headless_via_daemon(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> int:
    """Run a single prompt by connecting to a running daemon."""
```

**Dependencies**: `soothe.daemon`, `rendering.progress_renderer`, `soothe.ux.shared.progress_verbosity`

#### execution/standalone_runner.py
**Purpose**: Execute in standalone mode

**Public API**:
```python
async def run_headless_standalone(
    cfg: SootheConfig,
    prompt: str,
    *,
    thread_id: str | None = None,
    output_format: str = "text",
    autonomous: bool = False,
    max_iterations: int | None = None,
) -> None:
    """Run a single prompt in standalone mode."""
```

**Dependencies**: `soothe.core.runner`, `rendering.progress_renderer`, `soothe.ux.shared.progress_verbosity`

#### execution/postgres_check.py
**Purpose**: Check PostgreSQL availability

**Public API**:
```python
def check_postgres_available() -> bool:
    """Check if PostgreSQL is running on localhost:5432."""
```

#### rendering/progress_renderer.py
**Purpose**: Render progress events to stdout/stderr

**Public API**:
```python
def render_progress_event(data: dict, *, prefix: str | None = None) -> None:
    """Render a progress event to stdout/stderr."""
```

**Dependencies**: None

#### commands/run_cmd.py
**Purpose**: Handle `soothe run` command

**Public API**:
```python
def run(
    prompt: str | None,
    config: str | None,
    thread: str | None,
    *,
    no_tui: bool,
    autonomous: bool,
    max_iterations: int | None,
    output_format: str,
    progress_verbosity: Literal["minimal", "normal", "detailed", "debug"] | None,
) -> None:
    """Run the Soothe agent with a prompt or in interactive TUI mode."""
```

**Dependencies**: `core.logging_setup`, `core.config_loader`, `core.migrations`, `execution.*`

#### commands/config_cmd.py
**Purpose**: Handle `soothe config` command

**Public API**:
```python
def config(
    config: str | None,
    *,
    list_profiles: bool,
    profile: str | None,
    key: str | None,
    value: str | None,
) -> None:
    """Manage Soothe configuration."""
```

#### commands/thread_cmd.py
**Purpose**: Handle `soothe thread *` commands

**Public API**:
```python
def thread_list(...) -> None:
    """List active threads."""

def thread_resume(...) -> None:
    """Resume a thread."""

def thread_archive(...) -> None:
    """Archive a thread."""

def thread_inspect(...) -> None:
    """Inspect thread state."""

def thread_delete(...) -> None:
    """Delete a thread."""

def thread_export(...) -> None:
    """Export thread to file."""
```

### Dependency Flow

```
main.py (orchestrator)
    ↓
commands/ (command handlers)
    ↓
execution/ (execution modes)
    ↓
rendering/ (output formatting)
    ↓
core/ (low-level utilities)
```

**Rules**:
- Commands can import execution, rendering, and core
- Execution can import rendering and core
- Rendering can only import standard library
- Core can only import soothe.config

### Naming Conventions

- **Public functions**: No underscore prefix (e.g., `run_headless`, `load_config`)
- **Private helpers**: Underscore prefix (e.g., `_render_action_start`)
- **Module names**: snake_case (e.g., `daemon_runner.py`)
- **Package names**: snake_case (e.g., `execution/`)

## Implementation

### Migration Strategy

**Phase 1**: Create module structure
- Create directories: `core/`, `execution/`, `commands/`, `rendering/`
- Add `__init__.py` files with proper exports

**Phase 2**: Extract core utilities (no dependencies)
- Extract `logging_setup.py`
- Extract `config_loader.py`
- Extract `migrations.py`
- Update imports in main.py

**Phase 3**: Extract rendering (no dependencies)
- Extract `progress_renderer.py`
- Update imports in main.py

**Phase 4**: Extract execution modes
- Extract `postgres_check.py`
- Extract `tui.py`
- Extract `daemon_runner.py`
- Extract `standalone_runner.py`
- Extract `headless.py`
- Update imports in main.py

**Phase 5**: Extract commands
- Extract `run_cmd.py`
- Extract `config_cmd.py`
- Extract `attach_cmd.py`
- Extract `init_cmd.py`
- Extract `server_cmd.py`
- Extract `thread_cmd.py`
- Extract `status_cmd.py`
- Update imports in main.py

**Phase 6**: Simplify main.py
- Remove all extracted code
- Keep only app initialization and command registration

### Breaking Changes

This is a **cut change** with no backwards compatibility:

1. **Function renames**: Remove `_` prefix from public functions
   - `_load_config` → `load_config`
   - `_run_tui` → `run_tui`
   - `_run_headless` → `run_headless`
   - `_check_postgres_available` → `check_postgres_available`

2. **Module moves**: Functions moved to new locations
   - Old: `from soothe.ux.main import _load_config`
   - New: `from soothe.ux.core.config_loader import load_config`

3. **Internal state moved**:
   - `_config_cache` moved to `core/config_loader.py`
   - `_DAEMON_FALLBACK_EXIT_CODE` moved to `execution/headless.py`

## Testing

### Unit Tests (Future)

Each module should have corresponding test file:
- `tests/cli/core/test_logging_setup.py`
- `tests/cli/core/test_config_loader.py`
- `tests/cli/execution/test_headless.py`
- `tests/cli/rendering/test_progress_renderer.py`

### Integration Tests

Test that CLI still works end-to-end:
- `soothe run "test prompt"`
- `soothe config --list-profiles`
- `soothe thread list`

## Open Questions

None - this is a straightforward refactoring with clear scope.

## References

- Original code: `src/soothe/cli/main.py` (1574 lines)
- Related modules: `commands.py`, `daemon.py`, `tui_app.py`
