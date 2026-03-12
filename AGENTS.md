# Soothe Development Rules

## Mandatory Constraints

- **Built on deepagents and langchain ecosystem.** DO NOT reinvent modules if the langchain
  ecosystem already provides them. Always check langchain-core, langchain-community, and
  deepagents before implementing any tool, middleware, or agent pattern.
- Subagents MUST use deepagents' `SubAgent` or `CompiledSubAgent` types.
- Tools MUST use langchain's `BaseTool` subclass or `@tool` decorator.
- MCP integration MUST use `langchain-mcp-adapters`.
- Skills MUST use deepagents' `SkillsMiddleware` (SKILL.md format).
- Memory MUST use deepagents' `MemoryMiddleware` (AGENTS.md format).

## Code Standards

- Python >=3.11, type hints on all public functions.
- Google-style docstrings with Args, Returns, Raises sections.
- Use `ruff` for linting and formatting.
- Unit tests for all new features; `pytest` with `asyncio_mode = "auto"`.
- No bare `except:`; use typed exception handling.
- Single backticks for inline code in docstrings (not Sphinx double backticks).

## Architecture

- `create_soothe_agent()` wraps `create_deep_agent()` -- it is the main entry point.
- `SootheConfig` (Pydantic Settings) drives declarative agent configuration.
- Custom subagents live in `src/soothe/subagents/`.
- Custom tools live in `src/soothe/tools/`.
- MCP loading lives in `src/soothe/mcp/`.

## What deepagents Provides (DO NOT reimplement)

- File operations: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Shell execution: `execute`
- Task tracking: `write_todos`
- SubAgent spawning: `task` tool
- Skills: SKILL.md discovery
- Memory: AGENTS.md loading
- Summarization: auto-compaction
- Middleware: TodoList, Filesystem, SubAgent, Summarization, PromptCaching

## What langchain Provides (DO NOT reimplement)

- Web search: `TavilySearchResults`, `DuckDuckGoSearchRun`
- ArXiv: `ArxivQueryRun`
- Wikipedia: `WikipediaQueryRun`
- GitHub: `GitHubAPIWrapper`
- Gmail: `GmailToolkit`
- Python REPL: `PythonREPLTool`
- Document loaders: `PyPDFLoader`, `Docx2txtLoader`, etc.
