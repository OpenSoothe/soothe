# Soothe Project Setup and Noesium Migration Guide

**Status**: Active  
**Created**: 2026-03-12  

## Overview

This guide covers setting up the Soothe Python project as a multi-agent harness built on
deepagents + langchain/langgraph, and migrating valuable subagents and tools from noesium
(skipping those already available in the langchain ecosystem).

### Core Principles

1. **Built on deepagents and langchain** -- never reinvent modules the ecosystem already owns.
2. **Migrate, don't duplicate** -- only port noesium components that have no langchain equivalent.
3. **Extensible by design** -- easy to add new subagents, tools, MCP servers, and Skills.

## Architecture

```
                          ┌─────────────────────────────────┐
                          │            Soothe                │
                          │                                  │
                          │  create_soothe_agent()           │
                          │  SootheConfig                    │
                          │  Custom SubAgents & Tools        │
                          │  MCP / Skills integration        │
                          └──────────┬──────────────────────┘
                                     │ wraps
                          ┌──────────▼──────────────────────┐
                          │       deepagents SDK             │
                          │                                  │
                          │  create_deep_agent()             │
                          │  Middleware (FS, Todos, SubAgent) │
                          │  SKILL.md / AGENTS.md support    │
                          └──────────┬──────────────────────┘
                                     │ built on
                          ┌──────────▼──────────────────────┐
                          │  LangChain / LangGraph           │
                          │                                  │
                          │  create_agent(), StateGraph      │
                          │  Chat Models, Community Tools    │
                          │  langchain-mcp-adapters          │
                          └─────────────────────────────────┘
```

## Phase 1: Project Scaffold

### Directory Structure

```
soothe/
  pyproject.toml                  # Package metadata and dependencies
  AGENTS.md                       # Root rules (mandatory constraints)
  src/soothe/
    __init__.py                   # Public exports
    agent.py                      # create_soothe_agent()
    config.py                     # SootheConfig (Pydantic Settings)
    subagents/
      __init__.py                 # Subagent registry and exports
      research.py                 # Tacitus migration (CompiledSubAgent)
      planner.py                  # PlanAgent migration (SubAgent)
      scout.py                    # ExploreAgent migration, renamed (SubAgent)
      browser.py                  # BrowserUseAgent migration (CompiledSubAgent)
    tools/
      __init__.py                 # Tool registry and exports
      jina.py                     # Jina Reader web content extraction
      serper.py                   # Multi-type Serper search
      image.py                    # Vision-model image analysis
      audio.py                    # Audio transcription
      video.py                    # Video analysis
      tabular.py                  # Tabular data inspection
    mcp/
      __init__.py
      loader.py                   # MCP server loading (wraps langchain-mcp-adapters)
  tests/
    unit_tests/
    integration_tests/
  examples/
    basic_agent.py
    research_example.py
    scout_example.py
    browser_example.py
```

### Dependencies

Core (required):

| Package | Version | Purpose |
|---------|---------|---------|
| deepagents | >=0.4.10,<1.0.0 | Agent harness (file ops, todos, subagents, skills, memory) |
| langchain-core | >=1.2.18,<2.0.0 | Core abstractions (BaseTool, BaseChatModel) |
| langchain | >=1.2.11,<2.0.0 | Agent creation, middleware |
| langgraph | >=0.4.0,<1.0.0 | StateGraph runtime |
| langchain-mcp-adapters | >=0.2.0,<1.0.0 | MCP server integration |
| pydantic | >=2.0.0,<3.0.0 | Configuration models |
| pydantic-settings | >=2.0.0,<3.0.0 | Env-var driven config |

Optional extras:

| Extra | Packages | For |
|-------|----------|-----|
| research | tavily-python | Research subagent (Tavily search) |
| browser | cdp-use | Browser subagent (CDP automation) |
| serper | requests | Extended Serper search |
| jina | aiohttp | Jina Reader |
| media | pillow, openai | Image/audio/video analysis |
| all | (all of the above) | Everything |

### AGENTS.md Rules

The root `AGENTS.md` establishes mandatory constraints for all development:

- Built on deepagents and langchain ecosystem; do NOT reinvent existing modules.
- Subagents use deepagents' `SubAgent`/`CompiledSubAgent` types.
- Tools use langchain's `BaseTool` / `@tool` decorator.
- MCP via `langchain-mcp-adapters`.
- Skills via deepagents' `SkillsMiddleware` (SKILL.md format).

## Phase 2: Config and Agent Factory

### SootheConfig

Pydantic Settings model with env-var support:

- `model` -- LLM model string (default: `"claude-sonnet-4-6"`)
- `subagents` -- dict of subagent name to enable/config
- `tools` -- list of enabled tool group names
- `mcp_servers` -- list of MCP server configs (Claude Desktop JSON format)
- `skills` -- list of SKILL.md source paths
- `memory` -- list of AGENTS.md file paths
- `backend` -- backend type (state, filesystem, etc.)

### create_soothe_agent()

Thin wrapper around `create_deep_agent()`:

1. Read `SootheConfig` (or accept overrides)
2. Resolve enabled subagents into `SubAgent`/`CompiledSubAgent` list
3. Resolve enabled tools into `BaseTool` list
4. Load MCP tools via `langchain-mcp-adapters`
5. Call `create_deep_agent(model, tools, subagents, skills, memory, ...)`
6. Return `CompiledStateGraph`

## Phase 3: MCP Integration

Port the config-driven MCP loading pattern from deepagents CLI (`mcp_tools.py`):

- Support Claude Desktop format `.mcp.json` files
- Support stdio and HTTP/SSE transports
- `MultiServerMCPClient` for concurrent server connections
- MCP tools converted to langchain `BaseTool` and passed to `create_deep_agent()`

## Phase 4: Tool Migration

### What We Get For Free

These are NOT reimplemented:

| Noesium Tool | Use Instead | Source |
|---|---|---|
| bash, file_edit | deepagents built-in | `deepagents` |
| web_search (Tavily/DDG) | `TavilySearchResults`, `DuckDuckGoSearchRun` | `langchain-community` |
| arxiv | `ArxivQueryRun` | `langchain-community` |
| wikipedia | `WikipediaQueryRun` | `langchain-community` |
| github | `GitHubAPIWrapper` | `langchain-community` |
| gmail | `GmailToolkit` | `langchain-google-community` |
| python_executor | `PythonREPLTool` | `langchain-community` |
| memory | deepagents AGENTS.md | `deepagents` |
| user_interaction | `HumanInTheLoopMiddleware` | `deepagents` |
| document loaders | `PyPDFLoader`, etc. | `langchain-community` |

### Tools to Port

All implemented as langchain `BaseTool` subclasses with `_run()` and `_arun()`.

| Tool | Module | Noesium Source | Description |
|---|---|---|---|
| `JinaReaderTool` | `tools/jina.py` | `toolkits/jina_research/` | Web content extraction via Jina Reader API |
| `SerperSearchTool` | `tools/serper.py` | `toolkits/serper/` | Multi-type search (image, news, scholar, maps, video, places, lens) |
| `ImageAnalysisTool` | `tools/image.py` | `toolkits/image/` | Vision-model image analysis, OCR, comparison |
| `AudioTranscriptionTool` | `tools/audio.py` | `toolkits/audio/` | Audio transcription + Q&A (OpenAI Whisper) |
| `VideoAnalysisTool` | `tools/video.py` | `toolkits/video/` | Video analysis via multimodal models |
| `TabularDataTool` | `tools/tabular.py` | `toolkits/tabular_data/` | Column inspection, data summary, quality validation |

## Phase 5: Subagent Migration

All subagents are compatible with deepagents' `task` tool via `SubAgent` or `CompiledSubAgent`.

### 1. Research (from Tacitus)

- **Type**: `CompiledSubAgent` with custom LangGraph `StateGraph`
- **Source**: `noesium/src/noesium/subagents/tacitus/`
- **Workflow**: query generation -> multi-engine search -> reflection -> synthesis -> citations
- **Migration**:
  - Port iterative research loop as LangGraph `StateGraph`
  - Replace noesium search with langchain `TavilySearchResults` + optional Serper
  - Keep reflection and citation synthesis logic
  - Expose via `CompiledSubAgent` with `runnable`

### 2. Planner (from PlanAgent)

- **Type**: `SubAgent` dict (system prompt + tools)
- **Source**: `noesium/src/noesium/subagents/plan/`
- **Why needed**: deepagents only has `write_todos` (task tracker), not a structured planner.
  Planner provides context evaluation, dependency mapping, resource exploration, and
  structured plan generation.
- **Migration**:
  - Port planning system prompt (context evaluation, requirement analysis, structured plans)
  - Use deepagents built-in file tools + `write_todos` for plan output
  - Optionally compose with Scout for resource exploration

### 3. Scout (from ExploreAgent, renamed)

- **Type**: `SubAgent` dict (system prompt + tools)
- **Source**: `noesium/src/noesium/subagents/explore/`
- **Migration**:
  - Port exploration system prompt (target analysis, search strategy, reflection, synthesis)
  - Use deepagents built-in file tools (`ls`, `read_file`, `glob`, `grep`)
  - Include media tools (image, audio, video, tabular) as optional extras

### 4. Browser (from BrowserUseAgent)

- **Type**: `CompiledSubAgent` with custom LangGraph `StateGraph`
- **Source**: `noesium/src/noesium/subagents/bu/`
- **Migration**:
  - Port as LangGraph `StateGraph` with CDP-based browser control
  - Keep core browser tools (navigate, click, type, screenshot, scrape)
  - Lazy initialization (browser session starts only when invoked)
  - Dependency: `cdp-use` (optional extra)

### Skipped

| Noesium Subagent | Reason |
|---|---|
| Askura (conversation) | Covered by deepagents `generalPurpose` subagent |
| Davinci (scientific) | Placeholder (`NotImplementedError`) in noesium |

## Phase 6: Skills and Extensibility

### Skills

Use deepagents built-in `SkillsMiddleware` (SKILL.md format). No custom system needed.
Configure via `SootheConfig.skills` paths.

### Adding Custom SubAgents

```python
from soothe import create_soothe_agent
from deepagents.middleware.subagents import SubAgent

my_subagent: SubAgent = {
    "name": "my_agent",
    "description": "Does X when asked about Y",
    "system_prompt": "You are a specialist in...",
    "tools": [my_tool_1, my_tool_2],
}

agent = create_soothe_agent(
    subagents=[my_subagent],
    mcp_servers=[{"command": "npx", "args": ["-y", "@my/mcp-server"]}],
    skills=["/path/to/skills/"],
)
```

### Adding MCP Servers

```python
agent = create_soothe_agent(
    mcp_servers=[
        {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
        {"url": "https://my-mcp-server.example.com/sse", "transport": "sse"},
    ],
)
```

## Implementation Order

1. **Scaffold** -- `pyproject.toml`, `AGENTS.md`, package structure, `__init__.py` files
2. **Config** -- `SootheConfig` with Pydantic Settings
3. **Agent factory** -- `create_soothe_agent()` wrapping `create_deep_agent()`
4. **MCP loader** -- config-driven MCP tool loading
5. **Tools** -- jina, serper, image, audio, video, tabular (as `BaseTool` subclasses)
6. **Subagents** -- research, planner, scout, browser
7. **Examples and tests** -- basic usage, unit tests for config and tool wiring

## Verification Checklist

- [ ] `pyproject.toml` installs cleanly with `uv pip install -e .`
- [ ] `AGENTS.md` contains mandatory rules
- [ ] `create_soothe_agent()` returns a working `CompiledStateGraph`
- [ ] Config can be driven by env vars or explicit arguments
- [ ] MCP servers load and their tools appear in the agent
- [ ] Each migrated tool works standalone
- [ ] Each migrated subagent is invokable via the `task` tool
- [ ] Skills and memory paths are forwarded to deepagents
- [ ] Custom subagents can be added via the `subagents` parameter
