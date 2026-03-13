# Soothe Polish Pass

**Guide**: IG-013
**Title**: Comprehensive Soothe Polish Pass
**Created**: 2026-03-13
**Related RFCs**: RFC-0001, RFC-0002, RFC-0003, RFC-0004, RFC-0005
**Related IGs**: IG-010 (superseded for TUI), IG-011 (Skillify), IG-012 (Weaver)

## Overview

This guide covers a comprehensive polish pass across several Soothe subsystems:

1. **Infrastructure**: Move `InMemoryVectorStore` to `vector_store/`, extract shared `emit_progress`
2. **Skillify/Weaver resilience**: Handle indexing-not-ready state gracefully
3. **TUI overhaul**: Textual-based always-on layout with daemon mode for detach/attach
4. **CLI expansion**: Thread management, headless mode polish, ecosystem tools
5. **Examples and config**: Reorganize examples, update config files

## Prerequisites

- [x] RFC-0001 through RFC-0005 accepted
- [x] IG-011 (Skillify) and IG-012 (Weaver) implemented
- [x] IG-010 (TUI layout refresh) implemented (will be superseded)

## Scope

### Files created

- `src/soothe/vector_store/in_memory.py`
- `src/soothe/utils/_progress.py`
- `src/soothe/cli/daemon.py`
- `src/soothe/cli/tui_app.py`
- `config/soothe_home_config.yml`
- `examples/agents/` (new subfolder with moved + new examples)
- `examples/batch_tasks_example.py`

### Files modified

- `src/soothe/vector_store/__init__.py`
- `src/soothe/subagents/skillify/indexer.py`
- `src/soothe/subagents/skillify/retriever.py`
- `src/soothe/subagents/skillify/__init__.py`
- `src/soothe/subagents/weaver/__init__.py`
- `src/soothe/subagents/research.py`
- `src/soothe/agent.py`
- `src/soothe/cli/main.py`
- `src/soothe/cli/commands.py`
- `src/soothe/cli/session.py`
- `config/config.yml`
- `config/env.example`
- `pyproject.toml`
- `docs/specs/RFC-0003.md`
- `docs/impl/010-tui-layout-history-refresh.md`

### Files deleted

- `src/soothe/subagents/skillify/_in_memory_vs.py`
- `examples/planner_example.py` (moved to `examples/agents/`)
- `examples/scout_example.py` (moved)
- `examples/research_example.py` (moved)
- `examples/browser_example.py` (moved)
- `examples/claude_example.py` (moved)

## Phase 1: Infrastructure Polish

### 1.1 Move InMemoryVectorStore

Move `src/soothe/subagents/skillify/_in_memory_vs.py` to `src/soothe/vector_store/in_memory.py`.

Update `create_vector_store()` factory to support `"in_memory"` and `"none"` providers:

```python
if provider in ("in_memory", "none"):
    from soothe.vector_store.in_memory import InMemoryVectorStore
    return InMemoryVectorStore(collection=collection)
```

Update all import sites:
- `src/soothe/subagents/skillify/__init__.py`
- `src/soothe/subagents/weaver/__init__.py`

Delete the old file.

### 1.2 Extract shared emit_progress

Create `src/soothe/utils/_progress.py`:

```python
def emit_progress(event: dict[str, Any], logger: logging.Logger) -> None:
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        if writer:
            writer(event)
    except (ImportError, RuntimeError):
        pass
    logger.info("Progress: %s", event)
```

Replace the three duplicate `_emit_progress` definitions in research.py,
skillify/__init__.py, and weaver/__init__.py with imports.

## Phase 2: Skillify/Weaver Resilience

### 2.1 Skillify indexing-not-ready

Add `asyncio.Event` to `SkillIndexer` that is set after first `run_once()` completes.
Pass to `SkillRetriever` which awaits it (bounded 10s timeout) before searching.
If timeout expires, return a `SkillBundle` with an informative message.

### 2.2 Weaver indexing tolerance

In Weaver's `_analyze_and_route`, check if Skillify retriever is ready.
If not, emit `soothe.weaver.skillify_pending`, await with 30s timeout, then retry.
Proceed best-effort if still not ready.

## Phase 3: TUI Overhaul

### 3.1 Add Textual dependency

Add `textual>=0.40.0` to core dependencies in `pyproject.toml`.

### 3.2 Daemon server

Create `src/soothe/cli/daemon.py` with `SootheDaemon` class:
- Unix domain socket at `~/.soothe/soothe.sock`
- PID file at `~/.soothe/soothe.pid`
- Newline-delimited JSON protocol for bidirectional IPC
- Wraps `SootheRunner` for async event streaming
- Supports multiple client connections (latest-client-wins for input)

### 3.3 Textual TUI

Create `src/soothe/cli/tui_app.py` with `SootheApp(App)`:
- Always-on two-column layout from startup
- Integrated chat input widget at bottom
- ConversationPanel, PlanPanel, ActivityPanel, SubagentPanel, StatusBar
- Connects to daemon, receives events, sends input
- `/detach` disconnects TUI, daemon keeps running

### 3.4 CLI integration

Update `main.py` with new commands: `attach`, `server start/stop/status`, `init`.
Expand `thread` subcommand group: `resume`, `inspect`, `delete`, `export`.

### 3.5 Headless mode polish

Polish `_run_headless` to render `soothe.*` events as structured progress lines,
support `--format jsonl`, and clean exit codes.

## Phase 4: Ecosystem Tools

Expand `_resolve_tools` in `agent.py` to support langchain ecosystem tools:
tavily, duckduckgo, arxiv, wikipedia, github, python_repl.

## Phase 5: Examples and Config

### 5.1 Reorganize examples

Move agent examples to `examples/agents/`, make SOOTHE_HOME-aware.
Add skillify, weaver, and batch task examples.

### 5.2 Update config files

Add Skillify/Weaver/ecosystem tools to `config/config.yml`.
Create `config/soothe_home_config.yml` template.
Update `config/env.example`.

### 5.3 Update specs

Update RFC-0003 for Textual + daemon architecture.
Rewrite IG-010 as the TUI implementation guide.

## Testing Strategy

- Unit tests for `InMemoryVectorStore` in its new location
- Unit tests for `emit_progress` utility
- Unit tests for `SkillRetriever` with not-ready indexer
- Unit tests for daemon protocol serialization
- Integration test for TUI startup/detach/attach cycle
- `ruff check` on all modified files

## Verification

- [ ] `InMemoryVectorStore` importable from `soothe.vector_store.in_memory`
- [ ] `create_vector_store("in_memory", ...)` works
- [ ] Old `_in_memory_vs.py` deleted
- [ ] `emit_progress` shared across research, skillify, weaver
- [ ] Skillify retriever returns informative message when indexing not ready
- [ ] Weaver waits for Skillify indexing with bounded timeout
- [ ] Textual TUI launches with two-column layout on `soothe run`
- [ ] Daemon starts/stops/detaches correctly
- [ ] `soothe thread inspect/delete/export` work
- [ ] Headless mode shows progress events
- [ ] Ecosystem tools configurable via `config.yml`
- [ ] All examples in `examples/agents/` work with SOOTHE_HOME
- [ ] `ruff check` passes on all touched files
