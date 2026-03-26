# IG-067: Research Subagent Migration

## Overview

**RFC**: RFC-0021 - Research Subagent
**Status**: In Progress
**Created**: 2026-03-26
**Author**: Claude (AI Agent)

## Objective

Convert the research tool and inquiry module into a unified, self-contained research subagent following RFC-0021 specifications.

## Background

Currently, research functionality is split across two modules:
- `src/soothe/tools/research/` - Tool wrapper
- `src/soothe/inquiry/` - Core engine and sources

This violates the self-containment principle and doesn't leverage the subagent abstraction that better fits research's multi-step, stateful nature.

## Implementation Plan

### Step 1: Create New Package Structure

**Location**: `src/soothe/subagents/research/`

```bash
mkdir -p src/soothe/subagents/research/sources
```

**Files to create**:
- `__init__.py` - Plugin definition and exports
- `implementation.py` - Subagent factory
- `events.py` - Research events (moved)
- `engine.py` - InquiryEngine (moved)
- `protocol.py` - InformationSource protocol (moved)
- `router.py` - SourceRouter (moved)
- `sources/__init__.py` - Source exports
- `sources/web.py` - WebSource (moved)
- `sources/academic.py` - AcademicSource (moved)
- `sources/filesystem.py` - FilesystemSource (moved)
- `sources/cli.py` - CLISource (moved)
- `sources/browser.py` - BrowserSource (moved)
- `sources/document.py` - DocumentSource (moved)
- `sources/_scoring.py` - Scoring helpers (moved)
```

### Step 2: Move inquiry Module

**Action**: Move all files from `src/soothe/inquiry/` to `src/soothe/subagents/research/`

**Files to move**:
1. `inquiry/protocol.py` → `subagents/research/protocol.py`
2. `inquiry/engine.py` → `subagents/research/engine.py`
3. `inquiry/router.py` → `subagents/research/router.py`
4. `inquiry/sources/*.py` → `subagents/research/sources/*.py`

**Update imports**:
- Change `soothe.inquiry` → `soothe.subagents.research`
- Update relative imports as needed

### Step 3: Move Research Events

**Action**: Move `src/soothe/tools/research/events.py` → `src/soothe/subagents/research/events.py`

**No changes needed**:
- Events remain the same
- Registration logic remains the same
- Only location changes

### Step 4: Create Subagent Implementation

**File**: `src/soothe/subagents/research/implementation.py`

**Key changes from tool to subagent**:

1. **Function signature**:
```python
# OLD (tool)
def create_research_tools(config, work_dir) -> list[BaseTool]

# NEW (subagent)
def create_research_subagent(model, config, context) -> CompiledSubAgent
```

2. **State schema**:
```python
class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int
```

3. **Return type**:
- Returns `CompiledStateGraph` (CompiledSubAgent)
- Wraps the existing InquiryEngine

4. **Integration**:
- Extract work_dir from context
- Resolve model from config
- Build sources based on domain
- Return compiled graph

### Step 5: Create Plugin Definition

**File**: `src/soothe/subagents/research/__init__.py`

**Structure**:
```python
from soothe_sdk import plugin, subagent

from .events import (
    ResearchAnalyzeEvent,
    ResearchCompletedEvent,
    # ... all other events
)
from .implementation import create_research_subagent

__all__ = [
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    # ... all exports
    "create_research_subagent",
    "ResearchPlugin",
]

@plugin(
    name="research",
    version="2.0.0",
    description="Deep research subagent with multi-source synthesis",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research subagent plugin."""

    @subagent(
        name="research",
        description="...",
    )
    async def create_subagent(self, model, config, context):
        """Create research subagent."""
        return create_research_subagent(model, config, context)
```

### Step 6: Update Source Imports

**File**: `src/soothe/subagents/research/engine.py`

**Changes**:
```python
# OLD
from soothe.tools.research.events import ResearchAnalyzeEvent, ...

# NEW
from .events import ResearchAnalyzeEvent, ...
```

**Also update**:
- Import path references to sources
- Import path references to protocol

### Step 7: Update All External Imports

**Find all files that import**:
- `from soothe.tools.research import ...`
- `from soothe.inquiry import ...`

**Update to**:
- `from soothe.subagents.research import ...`

**Likely locations**:
- `src/soothe/core/agent.py` - Agent factory
- `src/soothe/cli/commands/` - CLI commands
- `tests/` - Test files

### Step 8: Move Tests

**Actions**:
1. Move `tests/tools/research/` → `tests/subagents/research/`
2. Move `tests/inquiry/` → `tests/subagents/research/`
3. Update test imports
4. Update test fixtures

### Step 9: Remove Old Code

**Delete**:
1. `src/soothe/tools/research/` (entire package)
2. `src/soothe/inquiry/` (entire package)

**Verify**:
- No remaining imports reference old locations
- All tests pass

### Step 10: Update Documentation

**Files to update**:
- `CLAUDE.md` - Update module map
- `README.md` - Update examples (if any)
- Any user-facing documentation

## Detailed Implementation

### implementation.py

```python
"""Research subagent implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

from langgraph.graph.message import add_messages

from .engine import build_inquiry_engine
from .protocol import InquiryConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph import CompiledStateGraph

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class ResearchState(TypedDict):
    """State schema for research subagent."""

    messages: Annotated[list, add_messages]
    research_topic: str
    domain: str
    search_summaries: Annotated[list[str], add]
    sources_gathered: Annotated[list[str], add]
    max_loops: int
    loop_count: int


def create_research_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> CompiledStateGraph:
    """Create research subagent.

    Args:
        model: LLM for research operations.
        config: Soothe configuration.
        context: Context with work_dir and settings.

    Returns:
        Compiled LangGraph subagent.
    """
    from .sources.academic import AcademicSource
    from .sources.browser import BrowserSource
    from .sources.cli import CLISource
    from .sources.document import DocumentSource
    from .sources.filesystem import FilesystemSource
    from .sources.web import WebSource

    work_dir = context.get("work_dir", "")
    max_loops = context.get("max_loops", 3)
    domain = context.get("domain", "auto")

    # Build sources based on domain
    sources = _build_sources(domain, config, work_dir)

    # Create inquiry config
    inquiry_config = InquiryConfig(max_loops=max_loops)

    # Build and return the engine
    return build_inquiry_engine(model, sources, inquiry_config, _domain=domain)


def _build_sources(
    domain: str,
    config: SootheConfig,
    work_dir: str,
) -> list:
    """Build information sources for the given domain.

    Args:
        domain: Source domain hint.
        config: Soothe configuration.
        work_dir: Working directory.

    Returns:
        List of InformationSource instances.
    """
    from .sources.academic import AcademicSource
    from .sources.browser import BrowserSource
    from .sources.cli import CLISource
    from .sources.document import DocumentSource
    from .sources.filesystem import FilesystemSource
    from .sources.web import WebSource

    if domain == "web":
        return [WebSource(config=config), AcademicSource()]
    if domain == "code":
        return [FilesystemSource(work_dir=work_dir), CLISource(workspace_root=work_dir)]
    if domain == "deep":
        return [
            WebSource(config=config),
            AcademicSource(),
            FilesystemSource(work_dir=work_dir),
            CLISource(workspace_root=work_dir),
            DocumentSource(),
            BrowserSource(config=config),
        ]

    # auto domain
    return [
        WebSource(config=config),
        AcademicSource(),
        FilesystemSource(work_dir=work_dir),
        CLISource(workspace_root=work_dir),
        DocumentSource(),
    ]
```

### __init__.py

```python
"""Research subagent package."""

from typing import Any

from soothe_sdk import plugin, subagent

from .events import (
    ResearchAnalyzeEvent,
    ResearchCompletedEvent,
    ResearchGatherDoneEvent,
    ResearchGatherEvent,
    ResearchInternalLLMResponseEvent,
    ResearchQueriesGeneratedEvent,
    ResearchReflectEvent,
    ResearchReflectionDoneEvent,
    ResearchSubQuestionsEvent,
    ResearchSummarizeEvent,
    ResearchSynthesizeEvent,
)
from .implementation import create_research_subagent
from .protocol import (
    GatherContext,
    InformationSource,
    InquiryConfig,
    SourceResult,
)

__all__ = [
    # Events
    "ResearchAnalyzeEvent",
    "ResearchCompletedEvent",
    "ResearchGatherDoneEvent",
    "ResearchGatherEvent",
    "ResearchInternalLLMResponseEvent",
    "ResearchQueriesGeneratedEvent",
    "ResearchReflectEvent",
    "ResearchReflectionDoneEvent",
    "ResearchSubQuestionsEvent",
    "ResearchSummarizeEvent",
    "ResearchSynthesizeEvent",
    # Protocol
    "GatherContext",
    "InformationSource",
    "InquiryConfig",
    "SourceResult",
    # Factory
    "create_research_subagent",
    # Plugin
    "ResearchPlugin",
]


@plugin(
    name="research",
    version="2.0.0",
    description="Deep research subagent with multi-source synthesis",
    trust_level="built-in",
)
class ResearchPlugin:
    """Research subagent plugin.

    Provides deep research capability with iterative reflection
    across multiple information sources.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        """Initialize research subagent.

        Args:
            context: Plugin context with config and logger.
        """
        context.logger.info("Loaded research subagent")

    @subagent(
        name="research",
        description=(
            "Deep research subagent that iteratively searches, analyses, and synthesizes "
            "information from multiple sources. Use when a question requires thorough "
            "investigation, cross-validation, or multi-step research beyond a single "
            "web search. "
            "Inputs: `topic` (required, the research question), "
            "`domain` (optional, one of 'auto', 'web', 'code', 'deep'; default 'auto'). "
            "- 'web': Internet research (web search + academic papers). "
            "- 'code': Codebase exploration (filesystem + CLI tools). "
            "- 'deep': All sources combined for comprehensive research. "
            "- 'auto': Automatically selects sources based on the topic. "
            "Returns a comprehensive answer with citations."
        ),
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create research subagent.

        Args:
            model: LLM for research operations.
            config: Soothe configuration.
            context: Plugin context.

        Returns:
            Compiled LangGraph subagent.
        """
        return create_research_subagent(model, config, context.__dict__)
```

### engine.py Updates

**Key changes**:
```python
# OLD
from soothe.tools.research.events import (
    ResearchAnalyzeEvent,
    ...
)

# NEW
from .events import (
    ResearchAnalyzeEvent,
    ...
)
```

## Testing Strategy

### Unit Tests

1. **Test sources** (`tests/subagents/research/sources/test_*.py`):
   - Test each source in isolation
   - Mock external dependencies
   - Test relevance scoring

2. **Test router** (`tests/subagents/research/test_router.py`):
   - Test source selection logic
   - Test domain profiles
   - Test relevance-based routing

3. **Test engine** (`tests/subagents/research/test_engine.py`):
   - Test graph structure
   - Test state transitions
   - Test event emission

### Integration Tests

1. **Test subagent** (`tests/subagents/research/test_implementation.py`):
   - Test subagent creation
   - Test full research workflow
   - Test domain configurations

2. **Test plugin** (`tests/subagents/research/test_plugin.py`):
   - Test plugin loading
   - Test @subagent decorator
   - Test integration with Soothe

## Verification Checklist

- [ ] All files moved to new location
- [ ] All imports updated
- [ ] All tests pass (`make test-unit`)
- [ ] Linting passes (`make lint`)
- [ ] No references to old `tools/research/`
- [ ] No references to old `inquiry/`
- [ ] Events properly registered
- [ ] Plugin loads successfully
- [ ] Subagent creates successfully
- [ ] Research workflow executes correctly

## Risks and Mitigations

### Risk 1: Missing Import Updates
**Impact**: Runtime errors when old imports are used
**Mitigation**: Use `grep` to find all imports, verify each one

### Risk 2: Test Failures
**Impact**: Tests may fail due to import path changes
**Mitigation**: Run full test suite after migration, fix issues incrementally

### Risk 3: State Schema Mismatch
**Impact**: Tool state vs subagent state may have differences
**Mitigation**: Use existing InquiryState schema, adapt to CompiledSubAgent interface

## Success Criteria

1. ✅ All research code in `subagents/research/`
2. ✅ No code in `tools/research/` or `inquiry/`
3. ✅ All tests pass (900+ tests)
4. ✅ Zero linting errors
5. ✅ Plugin loads via `@plugin` decorator
6. ✅ Subagent creates via `@subagent` decorator
7. ✅ Events properly registered and emitted
8. ✅ Full research workflow functional

## Timeline

- Step 1-3 (Create structure, move files): 30 minutes
- Step 4-6 (Create implementation): 1 hour
- Step 7-8 (Update imports, tests): 1 hour
- Step 9-10 (Remove old code, verify): 30 minutes
- **Total**: ~3.5 hours

## References

- RFC-0021: Research Subagent
- RFC-0018: Plugin Extension System
- IG-047: Module Self-Containment Refactoring
- IG-052: Event System Optimization