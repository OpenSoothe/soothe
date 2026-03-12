---
name: create-subagent
description: >-
  Create new subagents for the Soothe multi-agent harness. Guides through choosing
  between SubAgent (declarative, deepagents-managed LLM loop) and CompiledSubAgent
  (custom LangGraph with own loop), implementing the factory function, wiring into
  config and agent.py, adding progress reporting, and writing tests. Use when adding
  a new subagent, wrapping an external library as a subagent, or extending agent
  capabilities with a specialist agent.
---

# Creating Subagents for Soothe

## Decision: SubAgent vs CompiledSubAgent

Choose the type before writing code.

| Criterion | SubAgent | CompiledSubAgent |
|---|---|---|
| LLM loop | deepagents manages it | You manage it (custom StateGraph) |
| Tools | deepagents file/shell tools + custom | Fully custom (or none) |
| System prompt | Provided as string | Embedded in graph logic |
| When to use | Specialist that needs standard tools (explore, plan, code) | Wrapper around external library with its own loop (browser-use, claude-agent-sdk) or custom multi-step pipeline (research) |
| Complexity | Low (~90 lines) | Medium-High (~150-400 lines) |
| Progress reporting | Not needed (deepagents streams natively) | Use `get_stream_writer()` for custom events |

**Rule of thumb**: If the subagent just needs an LLM with a focused system prompt and access to file/shell tools, use `SubAgent`. If it wraps an external SDK or needs a custom multi-node graph, use `CompiledSubAgent`.

## Step-by-Step Workflow

### Step 1: Create the subagent file

Create `src/soothe/subagents/{name}.py`. Follow the patterns below based on your chosen type.

### Step 2: Register in `__init__.py`

Add the factory import and `__all__` entry in `src/soothe/subagents/__init__.py`.

### Step 3: Register in `agent.py`

Add the factory to `_SUBAGENT_FACTORIES` dict in `src/soothe/agent.py`.

### Step 4: Add to default config

Add the subagent name to `SootheConfig.subagents` default dict in `src/soothe/config.py` (typically `enabled=False` for optional subagents).

### Step 5: Add optional dependency (CompiledSubAgent only)

If wrapping an external library, add it as an optional extra in `pyproject.toml` and include it in the `all` extra.

### Step 6: Write tests

Add unit tests in `tests/unit_tests/test_subagents.py`.

### Step 7: Add example

Create `examples/{name}_example.py` using the `_streaming.py` helper.

## Pattern A: SubAgent (Declarative)

Reference implementations: `scout.py`, `planner.py`

```python
"""MyAgent subagent -- brief purpose description."""

from __future__ import annotations

from deepagents.middleware.subagents import SubAgent
from langchain_core.language_models import BaseChatModel

MYAGENT_SYSTEM_PROMPT = """\
You are an expert {domain} agent.

## Responsibilities
1. ...
2. ...

## Process
1. **Step one** -- description using file tools.
2. **Step two** -- ...

## Output Format
- **Section**: description
"""

MYAGENT_DESCRIPTION = (
    "One-line description for the task tool. Include what it does "
    "and when to use it."
)


def create_myagent_subagent(
    model: str | BaseChatModel | None = None,
    **kwargs: object,
) -> SubAgent:
    """Create a MyAgent subagent spec.

    Args:
        model: Optional model override (string or BaseChatModel instance).
        **kwargs: Additional config (ignored for forward compat).

    Returns:
        `SubAgent` dict compatible with deepagents.
    """
    spec: SubAgent = {
        "name": "myagent",
        "description": MYAGENT_DESCRIPTION,
        "system_prompt": MYAGENT_SYSTEM_PROMPT,
    }
    if model:
        spec["model"] = model
    return spec
```

Key points:
- Accept `model: str | BaseChatModel | None` -- the caller may pass either
- Accept `**kwargs` for forward compatibility
- The `name` field is what appears in the `task` tool
- The `system_prompt` is injected by deepagents; the subagent gets standard file tools automatically

## Pattern B: CompiledSubAgent (Custom Graph)

Reference implementations: `browser.py` (external SDK), `claude.py` (external CLI), `research.py` (multi-node pipeline)

```python
"""MyAgent subagent -- wraps {library} as a CompiledSubAgent."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from deepagents.middleware.subagents import CompiledSubAgent
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)

MYAGENT_DESCRIPTION = (
    "One-line description for the task tool."
)


class _MyAgentState(dict):
    """State schema -- must include messages key."""
    messages: Annotated[list, add_messages]


def _build_myagent_graph(*, some_param: str = "default") -> Any:
    """Build and compile the LangGraph for this subagent."""

    async def _run_async(state: dict[str, Any]) -> dict[str, Any]:
        # 1. Import external library lazily (keeps it optional)
        # from my_library import Client

        # 2. Get stream writer for progress reporting
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
        except (ImportError, RuntimeError):
            writer = None

        def emit(event: dict[str, Any]) -> None:
            if writer:
                writer(event)
            logger.info("MyAgent progress: %s", event)

        # 3. Extract task from messages
        messages = state.get("messages", [])
        task = messages[-1].content if messages else ""

        # 4. Run the external library / custom logic
        emit({"type": "myagent_start", "task": task[:200]})
        try:
            result = "..."  # actual work here
        except Exception:
            logger.exception("MyAgent failed")
            result = "MyAgent encountered an error."

        emit({"type": "myagent_done"})
        return {"messages": [AIMessage(content=result)]}

    def run_sync(state: dict[str, Any]) -> dict[str, Any]:
        """Sync wrapper -- deepagents calls graph nodes synchronously."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(_run_async(state))
            finally:
                new_loop.close()
        else:
            return loop.run_until_complete(_run_async(state))

    graph = StateGraph(_MyAgentState)
    graph.add_node("run", run_sync)
    graph.add_edge(START, "run")
    graph.add_edge("run", END)
    return graph.compile()


def create_myagent_subagent(
    model: Any = None,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create a MyAgent subagent (CompiledSubAgent).

    Args:
        model: Model name or BaseChatModel (extract name if needed).
        **kwargs: Additional config forwarded to the graph builder.

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    runnable = _build_myagent_graph(**kwargs)
    return {
        "name": "myagent",
        "description": MYAGENT_DESCRIPTION,
        "runnable": runnable,
    }
```

Key points:
- State schema **must** have a `messages` key with `add_messages` reducer
- The final node **must** return `{"messages": [AIMessage(content=...)]}`
- Import external deps lazily inside the node function (keeps them optional)
- Sync wrapper is required -- deepagents calls graph nodes in a thread pool
- If the external library needs a model name string (not a langchain model object), extract it; see `_extract_model_name()` in `browser.py`

## Progress Reporting

CompiledSubAgents should emit custom events via `get_stream_writer()`:

```python
from langgraph.config import get_stream_writer

writer = get_stream_writer()
writer({"type": "myagent_step", "step": 1, "detail": "..."})
```

Consumers receive these as `"custom"` stream mode events when using:
```python
async for chunk in agent.astream(input, stream_mode=["messages", "updates", "custom"], subgraphs=True):
    namespace, mode, data = chunk
    if mode == "custom":
        print(data)  # {"type": "myagent_step", ...}
```

Always wrap in try/except -- `get_stream_writer()` raises `RuntimeError` when not streaming.

## Registration Checklist

After creating the subagent file:

1. **`src/soothe/subagents/__init__.py`** -- add import and `__all__` entry
2. **`src/soothe/agent.py`** -- add to `_SUBAGENT_FACTORIES` dict
3. **`src/soothe/config.py`** -- add to `SootheConfig.subagents` default factory
4. **`pyproject.toml`** -- add optional dependency group if needed
5. **`tests/unit_tests/test_subagents.py`** -- add factory smoke test
6. **`examples/{name}_example.py`** -- create example using `_streaming.py`

## Common Pitfalls

**Model type mismatch**: `_resolve_subagents` may pass a `BaseChatModel` instance instead of a string. If your subagent wraps an external library that needs a model name string, use `_extract_model_name()` (see `browser.py`).

**Async in sync context**: deepagents runs CompiledSubAgent nodes in a thread pool. If your node is async, you need the sync wrapper pattern with `asyncio.new_event_loop()` for the `loop.is_running()` case.

**Missing messages key**: CompiledSubAgent state MUST include `messages`. Without it, deepagents raises `ValueError` when extracting the result.

**Lazy imports**: Keep external library imports inside the node function. This lets the subagent be registered without requiring the optional dependency to be installed.

## Test Pattern

```python
class TestMyAgentSubagent:
    def test_creates_subagent_dict(self):
        from soothe.subagents.myagent import create_myagent_subagent
        spec = create_myagent_subagent()
        assert spec["name"] == "myagent"
        assert "description" in spec

    # For SubAgent:
    def test_has_system_prompt(self):
        spec = create_myagent_subagent()
        assert "system_prompt" in spec

    # For CompiledSubAgent:
    def test_has_runnable(self):
        spec = create_myagent_subagent()
        assert "runnable" in spec
```

## Example Pattern

```python
"""MyAgent example."""
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from soothe import SootheConfig, create_soothe_agent
from _streaming import run_with_streaming

load_dotenv()
PROJECT_ROOT = str(Path(__file__).parent.parent.resolve())

async def main() -> None:
    config = SootheConfig(
        workspace_dir=PROJECT_ROOT,
        subagents={
            "planner": {"enabled": False},
            "scout": {"enabled": False},
            "research": {"enabled": False},
            "browser": {"enabled": False},
            "claude": {"enabled": False},
            "myagent": {"enabled": True},
        },
    )
    agent = create_soothe_agent(config=config)
    await run_with_streaming(
        agent,
        [HumanMessage(content="Your task here.")],
        show_subagents=True,  # True for CompiledSubAgent to see custom events
    )

if __name__ == "__main__":
    asyncio.run(main())
```

## Reference Files

For detailed protocol definitions and architecture context:
- [RFC-0002: Architecture Design](../../docs/specs/RFC-0002.md) -- core protocol modules
- [IG-004: Ecosystem Capability Analysis](../../docs/impl/004-ecosystem-capability-analysis.md) -- what deepagents/langchain provide vs gaps
- [AGENTS.md](../../AGENTS.md) -- mandatory development constraints
