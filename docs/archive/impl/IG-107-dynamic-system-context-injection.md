# IG-107: Dynamic System Context Injection

**Implementation Guide for RFC-104**
**Created**: 2026-03-31
**Status**: Completed
**RFC**: [RFC-104](../specs/RFC-104-dynamic-system-context.md)

## Overview

This guide implements dynamic system context injection via `<SOOTHE_*>` XML tags into system prompts. The injection is classification-driven, adapting context depth based on task complexity.

## Implementation Tasks

| Task | Component | Status |
|------|-----------|--------|
| 1 | Add knowledge cutoff constants to models.py | ✅ Completed |
| 2 | Add get_git_status helper to workspace.py | ✅ Completed |
| 3 | Extend SystemPromptOptimizationMiddleware | ✅ Completed |
| 4 | Modify runner to inject context into state | ✅ Completed |
| 5 | Add unit tests | ✅ Completed |
| 6 | Run verification | ✅ Passed |

## Task 1: Knowledge Cutoff Constants

**File**: `src/soothe/config/models.py`

Add model knowledge cutoff mapping after existing model configurations:

```python
MODEL_KNOWLEDGE_CUTOFFS: dict[str, str] = {
    "claude-opus-4-6": "2025-05",
    "claude-sonnet-4-6": "2025-05",
    "claude-haiku-4-5": "2025-10",
    "claude-3-5-sonnet": "2025-04",
    "claude-3-5-haiku": "2025-04",
    "claude-3-opus": "2025-02",
    "gpt-4o": "2025-03",
    "gpt-4-turbo": "2025-01",
    "default": "2025-01",
}

def get_knowledge_cutoff(model_id: str) -> str:
    """Get knowledge cutoff date for model."""
    if ":" in model_id:
        model_id = model_id.split(":")[-1]
    return MODEL_KNOWLEDGE_CUTOFFS.get(model_id, MODEL_KNOWLEDGE_CUTOFFS["default"])
```

## Task 2: Git Status Helper

**File**: `src/soothe/safety/workspace.py`

Add async git status collection function. Must handle:
- Non-git directories (return None)
- Git command timeouts (2 second limit per command)
- Missing git binary (return None)

Key implementation points:
- Use `asyncio.to_thread()` for subprocess calls
- Truncate git status to 20 lines
- Parse main branch from symbolic-ref output

## Task 3: Middleware Extension

**File**: `src/soothe/middleware/system_prompt_optimization.py`

Add four section builder methods:
1. `_build_environment_section()` - platform, shell, model, cutoff
2. `_build_workspace_section(workspace, git_status)` - cwd, git info
3. `_build_thread_section(thread_context)` - thread ID, goals, plan
4. `_build_protocols_section(protocol_summary)` - active protocols

Modify `_get_prompt_for_complexity()` to:
- Accept state parameter
- Build sections based on complexity (chitchat/medium/complex)
- Append sections to base prompt

Update `modify_request()` to pass state to prompt builder.

## Task 4: Runner State Injection

**File**: `src/soothe/core/runner/_runner_phases.py`

In `_pre_stream_independent()`:
- Collect workspace from FrameworkFilesystem.get_current_workspace()
- Call get_git_status() for medium/complex tasks
- Build thread_context dict
- Build protocol_summary dict
- Attach to state object

In `_stream_phase()`:
- Pass collected context in stream_input dict

## Task 5: Unit Tests

**File**: `tests/unit/test_dynamic_system_context.py`

Test cases:
- `_build_environment_section()` returns valid XML
- `_build_workspace_section()` handles git and non-git
- `_build_thread_section()` handles empty goals
- `_build_protocols_section()` handles no protocols
- Complexity mapping correct (chitchat → none, medium → 2, complex → 4)
- Git status timeout handling

## Task 6: Verification

Run `./scripts/verify_finally.sh` to ensure:
- Code formatting passes
- Linting has zero errors
- All unit tests pass

## Dependencies

- RFC-103 (Thread-Aware Workspace) must be implemented for workspace ContextVar
- Existing SystemPromptOptimizationMiddleware infrastructure

## Estimated Scope

~350-400 lines total across 4 files + tests.