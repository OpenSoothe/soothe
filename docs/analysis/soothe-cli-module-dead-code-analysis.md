# soothe-cli Module Dead Code Analysis

**Analysis Date**: 2026-06-17
**Module**: `packages/soothe-cli`
**Scope**: Dead code, deprecated functions, backward compatibility shims

---

## Executive Summary

The soothe-cli module is relatively clean with **no explicit deprecation markers** found. However, there are:
- **6 backward compatibility shim modules** (RFC-413 migration, intentionally preserved)
- **1 unused module** (`runtime/task_scope.py` - no consumers)
- **1 potentially dead protocol** (`AsyncRendererProtocol` - defined but never used)
- **Several internal helper modules** with limited external usage

All shim modules are intentionally kept for backward compatibility and should not be removed without coordinated RFC-413 migration.

---

## 1. Backward Compatibility Shims (RFC-413 Migration)

These modules re-export from `soothe_sdk.display` to preserve legacy import paths. **Do NOT remove** until RFC-413 migration is complete and all import paths are updated.

| Shim Module | Source Package | Status |
|-------------|----------------|--------|
| `runtime/parse/_utils.py` | `soothe_sdk.display._text_utils` | Active shim, 0 direct imports |
| `runtime/parse/message_processing.py` | `soothe_sdk.display.message_processing` | Active shim, used by runtime & TUI |
| `runtime/parse/tool_message_format.py` | `soothe_sdk.display.tool_message_format` | Active shim, 0 direct imports |
| `runtime/parse/tool_result.py` | `soothe_sdk.display.tool_result` | Active shim, used by processor |
| `runtime/state/transcript.py` | `soothe_sdk.display.transcript_types` | Active shim, used by runtime/__init__.py |
| `runtime/wire/display_text.py` | `soothe_sdk.display.text_extract` | Active shim, 0 direct imports |

**Recommendation**: Keep all shim modules. They are documented as re-export shims in their docstrings. Import path migration is tracked under RFC-413.

---

## 2. Dead/Unused Modules

### 2.1 `runtime/task_scope.py` - **UNUSED**

**File**: `packages/soothe-cli/src/soothe_cli/runtime/task_scope.py`

**Exports**:
- `brief_task_tool_call_id(tool_call_id: str) -> str`
- `format_task_scope_prefix(tool_call_id: str, subagent_type: str) -> str`

**Usage Analysis**:
- **Zero imports** from this module
- Not exported through `runtime/__init__.py`
- Functions are defined but never called

**Recommendation**: **Remove** - No consumers found. The functionality may have been superseded by `soothe_sdk.ux.task_namespace` module.

---

## 3. Potentially Dead Code

### 3.1 `AsyncRendererProtocol` - **DEFINED BUT NEVER USED**

**File**: `packages/soothe-cli/src/soothe_cli/runtime/presentation/async_renderer_protocol.py`

**Description**: Defines async callback interface for TUI event rendering (mirroring sync `RendererProtocol`).

**Usage Analysis**:
- No classes implement this protocol
- No imports outside its own file
- TUI uses `RendererProtocol` through `EventProcessor`

**Recommendation**: **Investigate** - Either:
1. Remove if async rendering path was abandoned
2. Document if it's reserved for future async TUI architecture

---

## 4. Modules with Limited External Usage

### 4.1 `runtime/wire/message_text.py`

**Exports**:
- `wire_messageBody(msg)` - Used by chunk_filter.py
- `extract_text_from_message_content(content)` - Internal helper
- `extract_plain_text_from_stream_message(msg)` - Used by chunk_filter.py, tests

**Usage**: 2 consumers (chunk_filter.py, test file). Keep.

---

### 4.2 `runtime/wire/chunk_filter.py`

**Exports**:
- `updates_chunk_is_noop(data)` - Internal
- `message_has_tool_invocation_metadata(msg)` - Used by prepare.py
- `message_chunk_is_non_actionable(data)` - Internal
- `should_drop_stream_chunk_early(namespace, mode, data)` - Used by prepare.py

**Usage**: 2 consumers (prepare.py, test file). Keep.

---

### 4.3 `runtime/policy/tui_trace_log.py`

**Exports**:
- `log_tui_trace(tui_debug, event, **fields)` - Debug logging helper

**Usage**: 1 consumer (processor.py). Internal debug tool. Keep.

---

### 4.4 `runtime/presentation/explore_task_display.py`

**Exports**:
- `iter_concatenated_json_objects(raw)` - Internal helper
- `format_explore_task_json_blob_for_display(raw)` - Used by textual_adapter.py

**Usage**: 2 consumers (textual_adapter.py, test file). Keep.

---

## 5. Public API Usage Analysis

### 5.1 `runtime/__init__.py` Exports

| Export | External Usage | Status |
|--------|----------------|--------|
| `EventProcessor` | Tests only | Internal core class |
| `ProcessorState` | Tests only | Internal state |
| `DisplayPolicy` | Tests only | Internal policy |
| `RendererProtocol` | processor.py (TYPE_CHECKING), docs | Protocol definition |
| `TuiDaemonSession` | TUI modules, tests | Active |
| `MessageData`, `MessageType`, `ToolStatus` | TUI modules, tests | Active (re-export from SDK) |
| `PresentationEngine` | processor.py | Internal engine |
| `TurnEventPipeline` | TUI app modules | Active |
| Various helper functions | Internal use only | Re-exported for backward compat |

**Recommendation**: The runtime package exports many internal helpers for backward compatibility. Consider reducing public API surface after RFC-413 migration.

---

### 5.2 `config/__init__.py` Exports

| Export | Usage | Status |
|--------|-------|--------|
| `CLIConfig` | CLI commands, TUI, tests | Active |
| `load_config` | TUI, tests | Active |
| `set_runtime_config` | CLI main.py | Active |
| `reset_runtime_config` | Tests only | Test helper |

**Recommendation**: Keep all. `reset_runtime_config` is a test-only helper but harmless to export.

---

### 5.3 `cli/execution/__init__.py` Exports

| Export | Usage | Status |
|--------|-------|--------|
| `run_headless` | CLI commands, tests | Active |
| `run_tui` | CLI launcher.py | Active |

**Recommendation**: Keep all. Both are core execution entry points.

---

### 5.4 `tui/__init__.py` Exports

| Export | Usage | Status |
|--------|-------|--------|
| `SootheApp` | Launcher, tests | Active |
| `run_textual_tui` | Launcher | Active |

**Recommendation**: Keep all. Both are TUI entry points.

---

## 6. TUI Submodules Analysis

### 6.1 Private Utility Modules

| Module | Purpose | Usage |
|--------|---------|-------|
| `_version.py` | Version constants (DOCS_URL, PYPI_URL, etc.) | Used by update_check.py, welcome.py |
| `_env_vars.py` | Environment variable constants registry | Internal reference |
| `_cli_context.py` | CLIContext TypedDict | Used by textual_adapter.py |
| `tips.py` | SESSION_TIPS list + pick_session_tip() | Used by welcome.py |

**Recommendation**: Keep all. These are intentionally private utility modules.

---

## 7. Deprecated Markers Search Results

**Search Pattern**: `# deprecated|# TODO.*remove|# TODO: remove|DEPRECATED`

**Result**: **No matches found** in soothe-cli source code.

**Conclusion**: The module has no explicit deprecation markers.

---

## 8. Private Functions Analysis

Many modules define `_`-prefixed helper functions. These are internal implementation details and not dead code:

| Module | Private Functions | Purpose |
|--------|-------------------|---------|
| `runtime/parse/tool_call_resolution.py` | (none visible in grep) | Internal helpers |
| `runtime/state/file_tracker.py` | `_safe_read()`, `_count_lines()` | Internal helpers |
| `runtime/wire/chunk_filter.py` | `_dict_block_is_tool_invocation()` | Internal helper |
| `runtime/turn/pipeline.py` | `_SENTINEL` constant | Internal sentinel |
| `tui/command_registry.py` | (various) | Internal helpers |

**Recommendation**: These are standard private helpers. Not dead code.

---

## Summary & Recommendations

### Immediate Actions (Priority 1)

| Item | Location | Action |
|------|----------|--------|
| `runtime/task_scope.py` | Entire module | **Remove** - Zero consumers |
| `AsyncRendererProtocol` | `presentation/async_renderer_protocol.py` | **Investigate** - Either document purpose or remove |

### Deferred Actions (Priority 2 - After RFC-413)

| Item | Location | Action |
|------|----------|--------|
| Shim modules | `runtime/parse/*.py` | Coordinate removal with import path migration |
| `runtime/__init__.py` | Exports | Reduce public API surface after shim removal |

### Keep (No Changes)

| Item | Reason |
|------|--------|
| All shim modules (RFC-413) | Backward compatibility, intentional |
| `runtime/wire/message_text.py` | Used by chunk_filter |
| `runtime/wire/chunk_filter.py` | Used by prepare.py |
| `runtime/policy/tui_trace_log.py` | Debug tool |
| `runtime/presentation/explore_task_display.py` | Used by textual_adapter |
| All config exports | Core functionality |
| All execution exports | Core entry points |
| All TUI exports | Core entry points |
| TUI private utils (`_version`, `_env_vars`, `_cli_context`, `tips`) | Intentional private modules |

---

## Files to Remove

```
packages/soothe-cli/src/soothe_cli/runtime/task_scope.py
```

**Estimated line savings**: ~30 lines

---

## Files to Investigate

```
packages/soothe-cli/src/soothe_cli/runtime/presentation/async_renderer_protocol.py
```

If unused, can remove ~100 lines.