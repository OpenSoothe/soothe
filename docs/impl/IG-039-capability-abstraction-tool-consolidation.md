# IG-039: Capability Abstraction and Tool Consolidation

**Implements**: RFC-0014
**Created**: 2026-03-19

## Overview

Consolidate Soothe's ~23 individual tools into 6 capability-level tools,
extend `UnifiedClassification` with domain-scoped prompt guidance, and
remove redundant subagent prompt references.

## Changes

### Phase 1: Renamed Tools

1. **`websearch` tool** (`src/soothe/tools/websearch.py`)
   - Create thin wrapper around `WizsearchSearchTool` with `name="websearch"`
   - Register as `websearch` tool group in `_resolver_tools.py`
   - Keep `wizsearch` group for backward compat (resolves both search + crawl)

2. **`research` tool** (rename `inquiry` → `research`)
   - Update `InquiryTool.name` from `"inquiry"` to `"research"` in `src/soothe/tools/inquiry.py`
   - Update description to use "research" terminology
   - Register as `research` tool group in `_resolver_tools.py`
   - Keep `inquiry` group for backward compat

### Phase 2: New Consolidated Tools

3. **`workspace` tool** (`src/soothe/tools/workspace.py`)
   - Action-dispatched tool consolidating file_edit (6 tools) + cli's list_directory
   - Actions: `read`, `write`, `delete`, `search`, `list`, `info`
   - Delegates to existing tool classes internally
   - Inherits work_dir, allow_outside_workdir, backup config from file_edit

4. **`execute` tool** (`src/soothe/tools/execute.py`)
   - Mode-dispatched tool consolidating cli (5 tools) + python_executor
   - Modes: `shell`, `python`, `background`
   - Special: `kill <pid>` detected in shell mode
   - Inherits security controls (banned_commands) from CliTool

5. **`data` tool** (`src/soothe/tools/data.py`)
   - Extension-dispatched tool consolidating tabular (3 tools) + document (3 tools)
   - Operations: `inspect`, `summary`, `quality`, `extract`, `info`
   - Routes by file extension: .csv/.xlsx → tabular, .pdf/.docx → document

### Phase 3: Classification & Prompt Update

6. **Extend `UnifiedClassification`** (`src/soothe/core/unified_classifier.py`)
   - Add `capability_domains` field
   - Update classification prompt to produce domain list

7. **Domain-scoped prompt guidance** (`src/soothe/config/prompts.py`)
   - Replace monolithic `_TOOL_ORCHESTRATION_GUIDE` with per-domain guides
   - Create `_RESEARCH_GUIDE`, `_WORKSPACE_GUIDE`, `_EXECUTE_GUIDE`, `_DATA_GUIDE`

8. **Update `SystemPromptOptimizationMiddleware`** (`src/soothe/middleware/system_prompt_optimization.py`)
   - Inject only relevant domain guides based on `capability_domains`

### Phase 4: Config & Integration

9. **Update `_resolver_tools.py`**
   - Add `workspace`, `execute`, `data`, `websearch`, `research` tool groups
   - Keep old names as backward-compat aliases

10. **Update `SootheConfig` defaults** (`src/soothe/config/settings.py`)
    - Default tools: `[datetime, workspace, execute, data, websearch, research]`

11. **Update config template** (`src/soothe/config/config.yml`)
    - New default tools section
    - Document backward-compat aliases

12. **Update prompt guidance**
    - Remove `research` and `scout` subagent mentions from prompt guide
    - Simplify subagent list to: browser, claude, skillify, weaver

### Phase 5: Tests

13. **Unit tests** (`tests/unit_tests/test_consolidated_tools.py`)
    - Test workspace tool action dispatch
    - Test execute tool mode dispatch
    - Test data tool extension routing
    - Test websearch tool wrapper
    - Test research tool rename
    - Test backward compatibility of old tool group names

## File Inventory

| File | Action |
|------|--------|
| `src/soothe/tools/workspace.py` | Create |
| `src/soothe/tools/execute.py` | Create |
| `src/soothe/tools/data.py` | Create |
| `src/soothe/tools/websearch.py` | Create |
| `src/soothe/tools/inquiry.py` | Modify (rename) |
| `src/soothe/core/_resolver_tools.py` | Modify |
| `src/soothe/config/settings.py` | Modify |
| `src/soothe/config/config.yml` | Modify |
| `src/soothe/config/prompts.py` | Modify |
| `src/soothe/core/unified_classifier.py` | Modify |
| `src/soothe/middleware/system_prompt_optimization.py` | Modify |
| `tests/unit_tests/test_consolidated_tools.py` | Create |
| `docs/specs/RFC-0014.md` | Created |
| `docs/specs/rfc-index.md` | Modify |
