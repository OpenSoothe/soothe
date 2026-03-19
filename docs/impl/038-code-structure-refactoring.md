# IG-038: Code Structure Refactoring

**Guide**: 038
**Title**: Code Structure Refactoring for AI-Agent Processability
**Status**: In Progress
**Created**: 2026-03-19
**Related**: RFC-0001, RFC-0002, IG-014, IG-034

## Overview

Refactor the Soothe codebase to split large files (>400 lines), eliminate shared
code duplication, and improve modular boundaries. All functionality remains
unchanged -- this is a pure structural polish pass.

The primary goal is to make every module small enough for AI agents to read and
edit in a single context window while keeping the package hierarchy logical and
extensible.

## Motivation

1. **Large files** (>500 lines) are hard for AI agents to process in one pass.
2. **Shared code duplication** -- `_custom()`, `StreamChunk`, and constants are
   copy-pasted across four runner mixin files.
3. **Monolithic config.py** (1244 lines) mixes data models, prompt templates,
   environment resolution, and model/vector-store factory logic.
4. **Fat tool files** (`cli.py` 718L, `file_edit.py` 627L, `wizsearch.py` 593L)
   combine multiple tool classes with unrelated helpers.

## Changes

### 1. Shared runner utilities -- `core/_runner_shared.py`

Extract duplicated definitions from `runner.py`, `_runner_phases.py`,
`_runner_autonomous.py`, `_runner_steps.py`, and `_runner_checkpoint.py` into a
single module:

```
core/_runner_shared.py  (~30L)
  - StreamChunk type alias
  - _custom() helper
  - _MIN_MEMORY_STORAGE_LENGTH constant
```

All five files then import from `_runner_shared` instead of defining their own.

### 2. `config.py` (1244L) -> `config/` package

```
config/
├── __init__.py             # Re-exports SootheConfig + all models for backward compat
├── env.py                  # SOOTHE_HOME, _ENV_VAR_RE, _resolve_env(), _resolve_provider_env()
├── prompts.py              # _TOOL_ORCHESTRATION_GUIDE, _DEFAULT_SYSTEM_PROMPT,
│                           #   _SIMPLE_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT
├── models.py               # All Pydantic sub-models (ModelProviderConfig through SecurityConfig)
├── settings.py             # SootheConfig(BaseSettings) -- the main config class
├── model_factory.py        # create_chat_model(), create_embedding_model(), resolve_model()
└── vector_store_factory.py # Vector store creation/resolution helpers
```

`SootheConfig` keeps thin wrapper methods that delegate to factory modules.
`config/__init__.py` re-exports everything from the old `soothe.config` namespace.

### 3. `tools/cli.py` (718L) -> `tools/cli/` package

```
tools/cli/
├── __init__.py    # Re-exports get_tools()
├── security.py    # ANSI_ESCAPE, _BANNED_PATTERNS, _validate_command()
├── shell.py       # ShellHealthState, _PersistentShell, _get_or_create_shell(),
│                  #   _shell_instances, _cleanup_shell()
└── tools.py       # CLITool, CLIBatchTool, WorkingDirectoryTool, get_tools()
```

### 4. `tools/file_edit.py` (627L) -> `tools/file_edit/` package

```
tools/file_edit/
├── __init__.py   # Re-exports get_tools()
├── utils.py      # _normalize_workspace_relative_input(), path helpers
└── tools.py      # FileWriteTool, FileReadTool, FileDeleteTool,
                  #   GlobTool, GrepTool, FileEditTool, get_tools()
```

### 5. `tools/wizsearch.py` (593L) -> `tools/wizsearch/` package

```
tools/wizsearch/
├── __init__.py       # Re-exports get_tools()
├── availability.py   # WIZSEARCH_AVAILABLE sentinel, _check_wizsearch_available()
├── search.py         # WizsearchTool
└── crawl.py          # WizsearchCrawlTool, _T, _run_with_timeout()
```

### 6. `core/_runner_autonomous.py` (873L) -> split into 2 files

```
core/_runner_autonomous.py  (~450L)  # AutonomousMixin: _run_autonomous, _run_chitchat,
                                     #   iteration record building, top-level loop
core/_runner_goal_loop.py   (~420L)  # GoalLoopMixin: _autonomous_goal_iteration,
                                     #   _execute_goal_with_plan, reflections
```

`AutonomousMixin` inherits from `GoalLoopMixin` so the public interface on
`SootheRunner` stays unchanged.

### 7. `cli/daemon/server.py` (591L) -> split into 2 files

```
cli/daemon/server.py    (~350L)  # SootheDaemon class, startup/shutdown, socket listener
cli/daemon/handlers.py  (~240L)  # _ClientConn, client connection handling, message routing
```

## Backward Compatibility

Every split uses `__init__.py` re-exports so existing import paths continue to
work:

- `from soothe.config import SootheConfig` -- still works
- `from soothe.tools.cli import get_tools` -- still works
- `from soothe.tools.file_edit import get_tools` -- still works
- `from soothe.tools.wizsearch import get_tools` -- still works

No public API changes. No deprecation warnings (consistent with IG-014).

## Execution Order

1. Create `core/_runner_shared.py` and update all runner mixins
2. Convert `config.py` -> `config/` package
3. Convert `tools/cli.py` -> `tools/cli/` package
4. Convert `tools/file_edit.py` -> `tools/file_edit/` package
5. Convert `tools/wizsearch.py` -> `tools/wizsearch/` package
6. Split `core/_runner_autonomous.py` into two files
7. Split `cli/daemon/server.py` into two files
8. Run `make lint` and fix all issues
9. Verify all existing tests pass
