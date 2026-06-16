# Tools System

**Tools** are single-purpose utilities that the agent invokes directly for immediate operations. Soothe follows a **single-purpose tool design pattern** (RFC-101) where each tool performs exactly one operation, eliminating mode/action indirection that creates cognitive load for the LLM.

## Overview

### Design Philosophy

**Single-purpose tools** (RFC-101):
- One tool = one operation
- No mode/action parameters
- Clear, descriptive names
- Type-safe parameters
- Direct, predictable behavior

**Contrast with unified dispatch tools** (deprecated pattern):
```python
# BAD: Unified dispatch with mode/action (deprecated)
execute(mode="shell", action="run", command="ls")
execute(mode="python", action="run", code="print('hello')")

# GOOD: Single-purpose tools (current pattern)
run_command(command="ls")
run_python(code="print('hello')")
```

### Tool Naming Convention

Pattern: `{verb}_{noun}` or single verb for obvious operations.

| Category | Examples | Pattern |
|----------|----------|---------|
| Shell execution | `run_command`, `run_background`, `kill_process` | `{verb}_{noun}` |
| Python execution | `run_python` | `{verb}_{noun}` |
| File operations | `read_file`, `write_file`, `delete_file`, `glob`, `grep`, `ls` | `{verb}_{noun}` or verb |
| Code editing | `edit_file_lines`, `insert_lines`, `delete_lines`, `apply_diff` | `{verb}_{context}` |
| Media analysis | `analyze_image`, `transcribe_audio`, `analyze_video` | `{verb}_{noun}` |

### Tool Characteristics

| Characteristic | Value |
|----------------|-------|
| **Operations** | Single-shot |
| **State** | Stateless |
| **Duration** | Immediate (milliseconds to seconds) |
| **Complexity** | Simple |
| **Results** | Direct output |
| **LLM Calls** | Zero (no orchestration) |

## Built-in Toolkits

Soothe organizes tools into domain-specific **toolkits**. Each toolkit is a module containing related tools.

### 1. Execution Toolkit

**Location**: `toolkits/execution.py`

**Tools**:
- `run_command`: Execute shell commands synchronously (wraps `langchain_community.ShellTool`)
- `run_python`: Execute Python code (wraps `langchain_experimental.PythonREPLTool`)
- `run_background`: Run commands in background (daemon processes)
- `kill_process`: Terminate background processes

**Features**:
- Workspace boundary enforcement via `WorkspaceToolOperationSecurity`
- Virtual path translation for sandboxed environments
- Timeout enforcement (default: 60s, configurable)
- ANSI escape stripping for clean output

**Usage Examples**:
```python
# Shell command
result = run_command(command="ls -la", timeout=30)

# Python code
output = run_python(code="import math; print(math.pi)")

# Background process
pid = run_background(command="python train.py")

# Kill process
kill_process(pid=pid)
```

### 2. File Operations Toolkit

**Location**: `toolkits/file_ops.py`

**Tools**:
- `read_file`: Read file contents (paginated, capped at ~50 lines)
- `write_file`: Write new file
- `delete_file`: Delete file with optional backup
- `edit_file`: Edit existing file (exact string replacement)
- `edit_file_lines`: Replace line ranges (surgical edit)
- `insert_lines`: Insert content at specific line
- `delete_lines`: Delete line ranges
- `apply_diff`: Apply unified diff patch
- `glob`: Find files matching patterns
- `grep`: Search file contents
- `ls`: List directory contents
- `file_info`: Get file metadata (size, permissions, timestamps)

**Features**:
- Workspace boundary enforcement
- Backup before deletion (timestamped backups)
- Pagination for large files (offset/limit parameters)
- ANSI escape handling for binary files

**Usage Examples**:
```python
# Read file
content = read_file(file_path="/src/auth.py", limit=100)

# Write file
write_file(file_path="/src/new.py", content="def hello():\n    pass")

# Edit file (string replacement)
edit_file(file_path="/src/auth.py", old_string="old", new_string="new")

# Edit file (line range)
edit_file_lines(file_path="/src/auth.py", start_line=1, end_line=5, new_content="# New content")

# Insert lines
insert_lines(file_path="/src/auth.py", line=10, content="import os")

# Delete lines
delete_lines(file_path="/src/auth.py", start_line=5, end_line=10)

# Apply diff
apply_diff(file_path="/src/auth.py", diff="--- a/auth.py\n+++ b/auth.py\n...")

# Find files
files = glob(pattern="**/*.py", path="/src")

# Search contents
matches = grep(pattern="TODO", output_mode="content")

# List directory
entries = ls(path="/src")

# Get metadata
info = file_info(path="/src/auth.py")
```

### 3. Web Search Toolkit

**Location**: `toolkits/wizsearch.py`

**Tools**:
- `wizsearch_search`: Multi-engine web search (Tavily, DuckDuckGo, Brave)
- `wizsearch_crawl`: Extract clean content from URLs (headless browser)

**Features**:
- Multiple search engines (aggregated results)
- Clean content extraction (strips navigation, ads, boilerplate)
- Time-sensitive query support (current_datetime integration)
- Markdown/HTML/text output formats

**Usage Examples**:
```python
# Web search
results = wizsearch_search(query="Python asyncio patterns", max_results_per_engine=10)

# Crawl URL
content = wizsearch_crawl(url="https://docs.python.org/3/library/asyncio.html", content_format="markdown")
```

### 4. Academic Search Toolkit

**Location**: `toolkits/deepxiv.py`

**Tools**:
- `deepxiv_search`: Semantic paper search (arXiv, bioRxiv, medRxiv, PMC)
- `deepxiv_paper_brief`: Quick summary with TLDR
- `deepxiv_paper_metadata`: Full metadata (authors, abstract, sections)
- `deepxiv_read_section`: Read specific sections (token-efficient)
- `deepxiv_get_full_paper`: Get complete paper (WARNING: high token cost)
- `deepxiv_trending`: Trending papers based on social signals

**Features**:
- Semantic search (not keyword-based)
- Citation count tracking
- GitHub link discovery
- Section-level reading (token optimization)
- Social signal aggregation (Twitter, Reddit)

**Usage Examples**:
```python
# Search papers
papers = deepxiv_search(query="transformer architecture", size=10, categories=["cs.AI"])

# Get brief summary
brief = deepxiv_paper_brief(paper_id="2409.05591")

# Get metadata
meta = deepxiv_paper_metadata(paper_id="2409.05591")

# Read specific section
intro = deepxiv_read_section(paper_id="2409.05591", section_name="Introduction")

# Get trending papers
trending = deepxiv_trending(days=7, limit=10)
```

### 5. Audio/Video/Image Toolkit

**Location**: `toolkits/audio.py`, `toolkits/video.py`, `toolkits/image.py`

**Audio Tools**:
- `transcribe_audio`: Transcribe audio to text (OpenAI Whisper)
- `audio_qa`: Answer questions about audio content

**Video Tools**:
- `analyze_video`: Analyze video content (Google Gemini, requires GOOGLE_API_KEY)
- `get_video_info`: Get basic metadata (file size, format)

**Image Tools**:
- `analyze_image`: Analyze image with vision model
- `extract_text_from_image`: OCR extraction

**Usage Examples**:
```python
# Transcribe audio
transcript = transcribe_audio(audio_path="/audio/meeting.mp3")

# Ask about audio
answer = audio_qa(audio_path="/audio/meeting.mp3", question="What was discussed?")

# Analyze video
analysis = analyze_video(video_path="/video/demo.mp4", question="Describe the actions")

# Analyze image
description = analyze_image(image_path="/img/screenshot.png", prompt="Describe UI elements")

# Extract text from image
text = extract_text_from_image(image_path="/img/document.png")
```

### 6. Data Toolkit

**Location**: `toolkits/data.py`

**Tools**:
- `inspect_data`: Inspect data file structure (columns, types, samples)
- `summarize_data`: Get statistical summary
- `check_data_quality`: Check quality (missing values, duplicates, anomalies)
- `extract_text`: Extract text from documents (PDF, DOCX)
- `get_data_info`: Get file metadata (size, format, page count)
- `ask_about_file`: Query data/document content

**Features**:
- Tabular file support (CSV, Excel, JSON, Parquet)
- Document support (PDF, DOCX, TXT, MD)
- Statistical aggregation
- Quality validation

**Usage Examples**:
```python
# Inspect CSV
structure = inspect_data(file_path="/data/users.csv")

# Summarize data
stats = summarize_data(file_path="/data/users.csv")

# Check quality
quality = check_data_quality(file_path="/data/users.csv")

# Extract PDF text
text = extract_text(file_path="/docs/report.pdf")

# Query document
answer = ask_about_file(file_path="/docs/report.pdf", question="What is the main conclusion?")
```

### 7. HTTP Requests Toolkit

**Location**: `toolkits/http_requests.py`

**Tools**:
- `requests_get`: HTTP GET request
- `requests_post`: HTTP POST request
- `requests_patch`: HTTP PATCH request
- `requests_put`: HTTP PUT request
- `requests_delete`: HTTP DELETE request

**Usage Examples**:
```python
# GET request
response = requests_get(url="https://api.example.com/data")

# POST request
result = requests_post(text='{"url": "https://api.example.com/create", "data": {"key": "value"}}')

# DELETE request
status = requests_delete(url="https://api.example.com/item/123")
```

### 8. DateTime Toolkit

**Location**: `toolkits/datetime.py`

**Tools**:
- `current_datetime`: Get current date, time, day of week, timezone

**Features**:
- Timezone-aware
- Multiple formats (ISO, human-readable)

**Usage Example**:
```python
# Get current time
now = current_datetime()
# Returns: {"date": "2026-06-06", "time": "14:30:25", "day_of_week": "Friday", "timezone": "UTC+8"}
```

## Implementation Pattern

### Tool Structure

Each tool follows a consistent pattern:

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

class <ToolName>Input(BaseModel):
    """Input schema for <tool_name>."""
    param1: str = Field(description="Description of param1")
    param2: int = Field(default=0, description="Description of param2")

class <ToolName>Tool(BaseTool):
    """<Brief description>."""
    name: str = "<tool_name>"
    description: str = "<detailed description>"
    args_schema: type[BaseModel] = <ToolName>Input

    def _run(self, param1: str, param2: int = 0) -> str:
        """Execute tool synchronously."""
        # Implementation
        return "result"

    async def _arun(self, param1: str, param2: int = 0) -> str:
        """Execute tool asynchronously."""
        # Implementation
        return "result"
```

### Plugin Registration

Tools are registered via the plugin system (RFC-600):

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="my_tool", description="My custom tool")
    def my_tool(self, param: str) -> str:
        """Execute my custom tool."""
        return f"Result: {param}"
```

### Security Integration

All tools integrate with OperationSecurityProtocol:

```python
from soothe.protocols.operation_security import OperationSecurityContext

class MySecureTool(BaseTool):
    def _run(self, file_path: str, runtime: Any = None) -> str:
        # Resolve workspace
        workspace = resolve_workspace_for_tool_execution(runtime, fallback=work_dir)
        
        # Apply security
        security = WorkspaceToolOperationSecurity(workspace)
        allowed = security.check_path(file_path)
        
        if not allowed:
            raise PermissionError(f"Path {file_path} outside workspace")
        
        # Execute safely
        return do_work(file_path)
```

## Event Naming Convention

Tools emit events following RFC-101 naming patterns:

### Atomic Operations (Single-shot)

Pattern: `soothe.tool.<component>.<verb>`

```python
class ReadEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.read"] = "soothe.tool.file_ops.read"
    file_path: str

class WriteEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.write"] = "soothe.tool.file_ops.write"
    file_path: str
    content_length: int
```

### Async Operations (Observable Lifecycle)

Pattern: `soothe.tool.<component>.<action>_started/completed/failed`

```python
class SearchStartedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_started"] = "soothe.tool.file_ops.search_started"
    query: str

class SearchCompletedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_completed"] = "soothe.tool.file_ops.search_completed"
    results_count: int
    duration_ms: int

class SearchFailedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.search_failed"] = "soothe.tool.file_ops.search_failed"
    error: str
```

### Event Registration

```python
from soothe.core.event_catalog import register_event

register_event(ReadEvent, summary_template="File read: {file_path}")
register_event(SearchStartedEvent, summary_template="Search started: {query}")
register_event(SearchCompletedEvent, summary_template="Search found {results_count} results in {duration_ms}ms")
```

## Langchain Ecosystem Integration

Soothe prioritizes using langchain ecosystem tools when available:

### Direct Usage (No Reinvention)

| Tool | Source | Purpose |
|------|--------|---------|
| `run_command` | `langchain_community.ShellTool` | Shell execution |
| `run_python` | `langchain_experimental.PythonREPLTool` | Python REPL |
| `glob`, `grep`, `ls` | `deepagents.FilesystemMiddleware` | File operations |
| `read_file`, `write_file` | `deepagents.FilesystemMiddleware` | File I/O |
| `wizsearch_search` | `wizsearch` library | Web search |
| `transcribe_audio` | OpenAI Whisper | Audio transcription |
| `analyze_video` | Google Gemini | Video analysis |

### Extension Pattern

Only create custom tools when langchain ecosystem doesn't provide equivalent functionality.

**Example**: Soothe's `edit_file_lines`, `insert_lines`, `delete_lines` extend langchain's file tools with surgical editing capabilities not available in the ecosystem.

## Extension Pattern

### Creating a Custom Tool

1. **Define input schema**:
```python
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    """Input for my_tool."""
    target: str = Field(description="Target to process")
    mode: str = Field(default="standard", description="Processing mode")
```

2. **Create tool class**:
```python
from langchain_core.tools import BaseTool

class MyTool(BaseTool):
    """Process targets with configurable mode."""
    name: str = "my_tool"
    description: str = "Process a target with specific mode. Returns processed result."
    args_schema: type[BaseModel] = MyToolInput

    def _run(self, target: str, mode: str = "standard") -> str:
        """Execute synchronously."""
        result = process_target(target, mode)
        return f"Processed {target}: {result}"
```

3. **Register via plugin**:
```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0")
class MyToolsPlugin:
    @tool(name="my_tool", description="Process targets")
    def my_tool(self, target: str, mode: str = "standard") -> str:
        return process_target(target, mode)
```

4. **Add events** (optional):
```python
from soothe.core.event_catalog import register_event

class MyToolEvent(ToolEvent):
    type: str = "soothe.tool.my_tools.process"
    target: str
    mode: str

register_event(MyToolEvent)
```

5. **Run verification**:
```bash
./scripts/verify_finally.sh
```

### Best Practices

1. **Check langchain first**: Don't reinvent if ecosystem provides it
2. **Single-purpose**: One operation per tool
3. **Clear naming**: `{verb}_{noun}` pattern
4. **Type-safe**: Pydantic input schema with descriptions
5. **Security-aware**: Use OperationSecurityProtocol for workspace boundaries
6. **Event-emitting**: Register domain-specific events
7. **Well-documented**: Detailed description for LLM comprehension

## Integration Points

### Tool Resolution

Tools are resolved via `resolve_tools()` in the agent builder:

```python
from soothe.core.agent._resolver_tools import resolve_tools

# Resolve all tools from config
tools = resolve_tools(
    config.tools,          # Tool group names
    policy=policy,         # PolicyProtocol instance
    workspace=workspace,   # Workspace boundary
    runtime=runtime        # ToolRuntime context
)
```

### Policy Integration

All tool operations pass through PolicyProtocol:

```python
# Policy check before tool execution
allowed = await policy.check(
    Permission("tool", "invoke", "run_command")
)
if not allowed:
    raise PermissionError("Tool run_command not permitted")
```

### Workspace Security

Tools enforce workspace boundaries via OperationSecurityProtocol:

```python
# Resolve workspace
workspace = resolve_workspace_for_tool_execution(runtime, fallback=work_dir)

# Apply security
security = WorkspaceToolOperationSecurity(workspace)
allowed = security.check_path(file_path)

# Virtual path translation (if sandboxed)
translated = translate_virtual_paths_in_command(command, workspace, virtual_mode=True)
```

### ToolRuntime Context

Tools receive runtime context for workspace resolution:

```python
from langchain.tools import ToolRuntime  # Optional import

def my_tool(file_path: str, runtime: ToolRuntime = None) -> str:
    """Execute with runtime context."""
    workspace = resolve_workspace_for_tool_execution(runtime)
    return process_file(workspace / file_path)
```

## Related RFCs

| RFC | Title | Key Sections |
|-----|-------|--------------|
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface & Event Naming | §4-5 (naming, events) |
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | §2 (@tool decorator) |
| [RFC-102](../../specs/RFC-102-security-filesystem-policy.md) | Security Filesystem Policy | Workspace boundaries |
| [RFC-901](../../specs/RFC-901-operation-security-protocol.md) | Operation Security Protocol | Security integration |

## Troubleshooting

### Common Issues

1. **Tool not found in resolve_tools()**:
   - Check plugin registration
   - Verify `@tool` decorator
   - Ensure plugin loaded via discovery

2. **Workspace boundary violation**:
   - Use `resolve_workspace_for_tool_execution()`
   - Apply `WorkspaceToolOperationSecurity`

3. **Event registration missing**:
   - Call `register_event()` at module level
   - Import events package in plugin `__init__.py`

4. **Timeout exceeded**:
   - Increase timeout parameter
   - Use `run_background` for long-running commands

### Debugging Tips

```bash
# Enable debug logs
SOOTHE_LOG_LEVEL=DEBUG soothe -p "run ls"

# Check tool loading
grep -i "loaded.*tool" ~/.soothe/logs/soothe.log

# Verify event emission
grep -i "soothe.tool.*" ~/.soothe/logs/soothe.log
```

---

**Previous**: [Subagents Architecture](subagents.md) | **Next**: [MCP Integration](mcp.md)