---
title: "Tools System"
parent: Capabilities
grand_parent: Wiki
nav_order: 2
description: >-
  Single-purpose utilities the agent invokes for immediate operations, following the single-purpose tool design pattern.
---

# Tools System

**Tools** are single-purpose utilities that the agent invokes directly for immediate operations. Soothe follows a **single-purpose tool design pattern** (RFC-101) where each tool performs exactly one operation, eliminating the mode/action indirection that creates cognitive load for the LLM.

## Design Philosophy: Single-Purpose Tools

The core insight is that LLMs choose tools by reading their names and descriptions. A tool named `execute(mode="shell", action="run")` forces the model to reason about *two* decisions — what mode and what action — before invoking it. A tool named `run_command(command="ls")` requires only one. The single-purpose pattern reduces the decision space, improves tool-selection accuracy, and makes failure modes predictable.

**The pattern's rules:**
- One tool = one operation (no mode/action parameters)
- Naming convention: `{verb}_{noun}` (e.g., `read_file`, `run_command`)
- Type-safe parameters via Pydantic schemas with descriptions
- Direct, predictable behavior — no hidden side effects

The deprecated contrast is the "unified dispatch" anti-pattern, where a single `execute()` tool takes a `mode` parameter to switch between shell, python, and file operations. This is harder for the LLM to use correctly and harder to debug when it fails.

## Toolkit Organization

Soothe organizes tools into domain-specific **toolkits** — modules of related tools. This grouping is both organizational (code structure) and semantic (helps the agent understand capability domains).

| Toolkit | Domain | Key Tools |
|---------|--------|-----------|
| **execution** | Shell & Python execution | `run_command`, `run_python`, `run_background`, `kill_process` |
| **file_ops** | File I/O & editing | `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `ls` |
| **wizsearch** | Web search | `wizsearch_search`, `wizsearch_crawl` |
| **deepxiv** | Academic papers | `deepxiv_search`, `deepxiv_paper_brief`, `deepxiv_read_section` |
| **audio/video/image** | Media analysis | `transcribe_audio`, `analyze_video`, `analyze_image` |
| **data** | Data inspection | `inspect_data`, `summarize_data`, `check_data_quality` |
| **http_requests** | HTTP operations | `requests_get`, `requests_post`, `requests_delete` |
| **datetime** | Time utilities | `current_datetime` |

→ Source: `packages/soothe/src/soothe/toolkits/`

## Langchain Ecosystem Integration

A defining design decision: **Soothe only builds tools that the langchain ecosystem doesn't already provide.** The toolkits `__init__.py` is explicitly documented as "only those not available in the langchain ecosystem." This avoids duplication and leverages battle-tested implementations.

| Tool | Ecosystem Source |
|------|-----------------|
| `run_command` | wraps `langchain_community.ShellTool` |
| `run_python` | wraps `langchain_experimental.PythonREPLTool` |
| `read_file`, `write_file`, `glob`, `grep`, `ls` | from `deepagents.FilesystemMiddleware` |
| `wizsearch_search` | from `wizsearch` library |
| `transcribe_audio` | OpenAI Whisper |

Soothe's custom additions — `edit_file_lines`, `insert_lines`, `delete_lines`, `apply_diff` — extend langchain's file tools with **surgical editing** capabilities that don't exist in the ecosystem. These enable precise line-range edits instead of full-file rewrites, which is critical for large files where token efficiency matters.

## Security Model

All tools integrate with `OperationSecurityProtocol` for workspace boundary enforcement. The security model has three layers:

1. **Workspace resolution** — `resolve_workspace_for_tool_execution()` determines the active workspace from the runtime context, with a fallback to the daemon's work directory.
2. **Path checking** — `WorkspaceToolOperationSecurity` validates that all file paths fall within the workspace boundary, preventing access to files outside the sandbox.
3. **Virtual path translation** — for sandboxed environments, virtual paths are translated to real filesystem paths transparently.

Execution tools (shell, Python) additionally enforce timeouts (default 60s), strip ANSI escape sequences for clean output, and run background processes as daemons with PID tracking for termination.

## Event Naming Convention

Tools emit wire events following RFC-101 patterns. The naming differs by operation type:

- **Atomic operations** (single-shot, synchronous): `soothe.tool.<component>.<verb>` — e.g., `soothe.tool.file_ops.read`
- **Async operations** (observable lifecycle): `soothe.tool.<component>.<action>_started/completed/failed` — e.g., `soothe.tool.file_ops.search_started`

Events are registered at module load via `register_event()` and imported in the plugin's `__init__.py` for side-effect registration.

## Extension Pattern: Creating a Custom Tool

Before creating a custom tool, ask: **does langchain already provide this?** If yes, use the ecosystem version. If no, the pattern is:

1. Define a Pydantic input schema with `Field(description=...)` for each parameter — the description is what the LLM reads to decide usage.
2. Create a `BaseTool` subclass (or a simple callable) with a clear `name` and detailed `description`.
3. Register via `@tool` decorator on a `@plugin` class.
4. Optionally register domain events for observability.

A minimal example:

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="analyze_data", description="Analyze CSV data and return statistics")
    def analyze_data(self, file_path: str) -> dict:
        return {"rows": 100, "columns": 5}
```

For tools needing workspace security, resolve the workspace from the runtime context and apply `WorkspaceToolOperationSecurity` before any file access. Tools receive an optional `runtime` parameter for this purpose.

## Tool Resolution

Tools are resolved at agent-build time via `resolve_tools()`, which takes tool group names from config, a PolicyProtocol instance, workspace boundary, and runtime context. Policy checks (`tool:invoke:<name>`) gate which tools are available to the agent. The resolved tool set is passed to the `AgentBuilder`.

## Gotchas and Non-Obvious Behavior

- **Pagination**: `read_file` caps at ~50 lines by default — use `offset`/`limit` for large files. The agent must paginate explicitly; the tool won't auto-load entire files.
- **Backup before deletion**: `delete_file` creates timestamped backups in a `.backups` directory before deletion — this is a safety net, not optional.
- **Background processes**: `run_background` returns a PID immediately; the process runs as a daemon. Use `kill_process(pid)` to terminate. Long-running commands should always use background mode to avoid timeout.
- **`requests_post` signature**: takes a JSON string with `url` and `data` keys (not separate parameters), which is non-obvious — the agent must serialize the request body as a JSON string.
- **Deepxiv token cost**: `deepxiv_get_full_paper` can consume enormous token budgets — prefer `deepxiv_read_section` for token-efficient access to specific sections.

## Related RFCs

| RFC | Title |
|-----|-------|
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface & Event Naming |
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System (`@tool` decorator) |
| [RFC-901](../../specs/RFC-901-operation-security-protocol.md) | Operation Security Protocol |

---

**Previous**: [Subagents Architecture](subagents.md) | **Next**: [MCP Integration](mcp.md)
