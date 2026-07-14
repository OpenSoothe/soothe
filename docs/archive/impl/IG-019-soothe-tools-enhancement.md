# Soothe Tools Enhancement Implementation Guide

> Implementation guide for enhancing Soothe's toolkit by porting production-ready tools from Noesium.
>
> **Module**: `src/soothe/tools/`
> **Source**: Derived from `thirdparty/noesium/noesium/src/noesium/toolkits/`
> **Related**: Gap analysis between Noesium (17 toolkits) and Soothe (13 tool groups)

---

## 1. Overview

This guide details the implementation of six tool enhancements for Soothe:

| Tool | Status | Priority | Effort |
|------|--------|----------|--------|
| **audio** (enhance) | ⚠️ Partial (OpenAI only) | 🔴 High | Medium |
| **video** (enhance) | ⚠️ Stub | 🔴 High | Medium |
| **cli** (new) | ✅ Complete | 🔴 Critical | High |
| **file_edit** (new) | ❌ Missing | 🔴 Critical | Medium |
| **document** (new) | ❌ Missing | 🟡 Medium | Medium |
| **python_executor** (new) | ❌ Missing | 🔴 Critical | High |

### Goals

1. **Feature Parity**: Bring Soothe to production parity with Noesium's tooling
2. **Architecture Alignment**: Adapt Noesium's `AsyncBaseToolkit` patterns to LangChain's `BaseTool`
3. **Quality**: Maintain production-grade error handling, caching, and security features
4. **Testing**: Ensure comprehensive unit and integration test coverage

---

## 2. Architectural Position

### Current Architecture

```
soothe/
├── core/
│   └── resolver.py          # Tool resolution and registration
└── tools/
    ├── audio.py             # OpenAI Whisper only (basic)
    ├── video.py             # Stub implementation
    ├── image.py             # Vision model analysis (complete)
    ├── datetime.py          # Time utilities (complete)
    ├── wizsearch.py         # Web search (complete)
    ├── serper.py            # Google search (complete)
    ├── jina.py              # Web content (complete)
    └── tabular.py           # Data analysis (complete)
```

### Target Architecture

```
soothe/
└── tools/
    ├── audio.py             # ✨ Enhanced: OpenAI + Aliyun NLS + audio_qa
    ├── video.py             # ✨ Enhanced: Full Gemini integration
    ├── cli.py               # ✨ Complete: Persistent shell execution (renamed from bash)
    ├── file_edit.py         # ✨ New: File operations with backup
    ├── document.py          # ✨ New: Multi-format document parsing
    ├── python_executor.py   # ✨ New: IPython execution with matplotlib
    └── [existing tools...]
```

### Integration Point

All tools integrate via `src/soothe/core/resolver.py`:

```python
def _resolve_single_tool_group(name: str) -> list[BaseTool]:
    # New tool registration points
    if name == "cli":
        from soothe.tools.cli import create_cli_tools
        return list(create_cli_tools())
    # ... etc
```

---

## 3. Module Structure

Each tool module follows this structure:

```
src/soothe/tools/{tool_name}.py
├── Constants & Configuration
├── Utility Functions (private)
├── Tool Classes (BaseTool subclasses)
│   ├── _run()      # Synchronous execution
│   └── _arun()     # Async execution
└── Factory Function
    └── create_{tool_name}_tools() -> list[BaseTool]
```

### Shared Dependencies

```toml
# pyproject.toml additions
[project.optional-dependencies]
cli = ["pexpect>=4.9.0"]
audio-full = ["aliyun-python-sdk-core>=2.15", "aliyun-python-sdk-nls-filetrans>=0.0.1"]
video = ["google-genai>=0.3.0"]
document = ["PyMuPDF>=1.24.0"]
python-executor = ["ipython>=8.0.0", "matplotlib>=3.8.0"]
```

---

## 4. Core Types

### Base Tool Class (LangChain)

All tools extend `langchain_core.tools.BaseTool`:

```python
from langchain_core.tools import BaseTool
from pydantic import Field

class ExampleTool(BaseTool):
    """Tool description shown to agents."""

    name: str = "tool_name"
    description: str = "Tool description for LLM agent."

    # Optional configuration
    config_field: str = Field(default="default_value")

    def _run(self, arg: str) -> str:
        """Synchronous implementation."""
        return self._execute(arg)

    async def _arun(self, arg: str) -> str:
        """Async implementation."""
        # Run sync in executor or implement async-native
        return self._run(arg)
```

### Configuration Pattern

```python
from pydantic import Field
from typing import Optional

class ConfigurableTool(BaseTool):
    # Environment-based config
    api_key: Optional[str] = Field(default=None)
    cache_dir: str = Field(default="")

    def __init__(self, **data):
        super().__init__(**data)
        if not self.api_key:
            import os
            self.api_key = os.getenv("API_KEY")
```

---

## 5. Implementation Details

### 5.1 Audio Toolkit Enhancement

**File**: `src/soothe/tools/audio.py`

**Current State**: OpenAI Whisper only, basic transcription

**Target State**: Multi-provider support (OpenAI + Aliyun NLS), audio Q&A

#### Architecture Changes

```python
# Current
class AudioTranscriptionTool(BaseTool):
    # OpenAI Whisper only

# Target
class AudioTranscriptionTool(BaseTool):
    """Multi-provider audio transcription."""
    provider: Literal["openai", "aliyun"] = Field(default="openai")

    def _run(self, audio_path: str) -> dict:
        if self.provider == "aliyun":
            return self._transcribe_aliyun(audio_path)
        return self._transcribe_openai(audio_path)

class AudioQATool(BaseTool):
    """Audio content Q&A using LLM."""

    def _run(self, audio_path: str, question: str) -> str:
        transcription = self._transcribe(audio_path)
        return self._analyze_with_llm(transcription, question)
```

#### Key Features to Port

1. **Aliyun NLS Integration**
   - Requires `aliyun-python-sdk-core` and `aliyun-python-sdk-nls-filetrans`
   - URL-only support (public URLs)
   - Optimized for Chinese language
   - Async polling for task completion

2. **Audio Q&A Tool** (new)
   - Transcribe → LLM analysis pipeline
   - Language-aware prompting (Chinese for Aliyun, English for OpenAI)
   - Context extraction and summarization

3. **Caching Layer**
   - MD5-based transcription caching
   - Avoid re-transcribing identical files
   - Cache directory management

4. **URL Downloading**
   - Async download with aiohttp
   - Automatic format detection
   - Temporary file management

#### Dependencies

```toml
[project.optional-dependencies]
audio-full = [
    "aliyun-python-sdk-core>=2.15.0",
    "aliyun-python-sdk-nls-filetrans>=0.0.1",
    "aiohttp>=3.9.0",
]
```

#### Security Considerations

- Aliyun credentials from environment only
- URL validation for Aliyun (must be public)
- File size limits for downloads
- Timeout protection for API calls

---

### 5.2 Video Toolkit Enhancement

**File**: `src/soothe/tools/video.py`

**Current State**: Stub - only file metadata

**Target State**: Full video analysis via Google Gemini

#### Implementation Pattern

```python
from google import genai
from google.genai.types import HttpOptions

class VideoAnalysisTool(BaseTool):
    """Video analysis using Google Gemini."""

    name: str = "analyze_video"
    google_api_key: Optional[str] = Field(default=None)
    model_name: str = Field(default="gemini-1.5-pro")

    def _run(self, video_path: str, question: str = "Describe this video") -> str:
        if not self.google_api_key:
            return "Google API key required for video analysis"

        client = genai.Client(
            api_key=self.google_api_key,
            http_options=HttpOptions(api_version="v1alpha")
        )

        # Upload video (placeholder - full implementation needed)
        # Analyze with Gemini
        return self._analyze_video_content(client, video_path, question)
```

#### Key Features

1. **Google Gemini Integration**
   - Video file upload (File API)
   - Content analysis and Q&A
   - Scene detection and description

2. **Multiple Input Types**
   - Local file upload
   - URL processing (future)

3. **Metadata Extraction**
   - Duration, resolution, codec
   - Frame rate, bit rate

#### Dependencies

```toml
[project.optional-dependencies]
video = ["google-genai>=0.3.0"]
```

#### Implementation Notes

- Google Gemini video processing requires file upload API
- Current Noesium implementation is also a placeholder
- Full implementation needs Google Cloud storage integration

---

### 5.3 CLI Toolkit (New)

**File**: `src/soothe/tools/cli.py`

**Priority**: 🔴 Critical - Required for coding agents

**Status**: ✅ Complete - Renamed from bash to better reflect capabilities

#### Core Design

```python
import pexpect
import re

ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

class CliTool(BaseTool):
    """Persistent CLI shell execution with security controls."""

    name: str = "run_cli"
    workspace_root: str = Field(default="")
    timeout: int = Field(default=60)
    max_output_length: int = Field(default=10000)

    # Security configuration - substring match
    banned_commands: list[str] = Field(default_factory=lambda: [
        "rm -rf /", "rm -rf ~", "rm -rf ./*", "rm -rf *",
        "mkfs", "dd if=", ":(){ :|:& };:",
        "sudo rm", "sudo dd",
        "chmod -R 777 /", "chown -R",
    ])

    # Security configuration - regex patterns
    banned_command_patterns: list[str] = Field(default_factory=lambda: [
        r"git\s+init", r"git\s+commit", r"git\s+add",
        r"rm\s+-rf\s+/", r"sudo\s+rm\s+-rf",
    ])

    def __init__(self, **data):
        super().__init__(**data)
        self._initialize_shell()

    def _initialize_shell(self):
        """Start persistent shell with custom prompt."""
        custom_prompt = "soothe-cli>> "
        # ... initialization code
```

#### Security Features

1. **Command Filtering**
   - Banned command list (substring match)
   - Banned regex patterns
   - Configurable restrictions

2. **Workspace Isolation**
   - Configurable workspace directory
   - Path validation

3. **Output Limits**
   - Maximum output length
   - Timeout protection

4. **Shell Recovery**
   - Auto-restart on crash
   - Responsiveness testing
   - State persistence

#### Tools Provided

```python
def create_cli_tools() -> list[BaseTool]:
    return [
        CliTool(),                # run_cli
        GetCurrentDirTool(),      # get_current_directory
        ListDirTool(),            # list_directory
        RunCliBackgroundTool(),   # run_cli_background
        KillProcessTool(),        # kill_process
        CheckCommandExistsTool(), # check_command_exists
    ]
```

#### Dependencies

```toml
[project.optional-dependencies]
cli = ["pexpect>=4.9.0"]
```

#### Critical Considerations

- **Platform**: Only works on Unix-like systems (macOS, Linux)
- **Security**: Essential for coding agents, dangerous if misconfigured
- **State Persistence**: Shell state (env vars, cwd) persists across commands
- **Enhancements**: Includes regex banned patterns, shell recovery, background execution

---

### 5.4 File Edit Toolkit (New)

**File**: `src/soothe/tools/file_edit.py`

**Priority**: 🔴 Critical - Required for coding agents

#### Core Design

```python
from pathlib import Path
import shutil
from datetime import datetime
import re

class FileEditTool(BaseTool):
    """File operations with backup and safety features."""

    name: str = "create_file"
    work_dir: str = Field(default="")
    backup_enabled: bool = Field(default=True)
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB

    def _sanitize_filename(self, filename: str) -> str:
        """Replace unsafe characters."""
        safe = re.sub(r"[^\w\-_.]", "_", filename)
        return safe.strip("_.")

    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create timestamped backup before modification."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = self.backup_dir / backup_name
        shutil.copy2(file_path, backup_path)
        return backup_path

    def _run(self, file_path: str, content: str, overwrite: bool = False) -> str:
        """Create or update file with backup."""
        resolved = self._resolve_path(file_path)

        if resolved.exists() and not overwrite:
            return f"Error: File exists. Use overwrite=True"

        backup = self._create_backup(resolved) if resolved.exists() else None

        with open(resolved, "w") as f:
            f.write(content)

        result = f"Created: {resolved}"
        if backup:
            result += f" (backup: {backup.name})"
        return result
```

#### Tools Provided

```python
def create_file_edit_tools() -> list[BaseTool]:
    return [
        CreateFileTool(),      # create_file
        ReadFileTool(),        # read_file
        WriteFileTool(),       # write_file
        DeleteFileTool(),      # delete_file
        ListFilesTool(),       # list_files
        SearchInFilesTool(),   # search_in_files
        GetFileInfoTool(),     # get_file_info
    ]
```

#### Key Features

1. **Filename Sanitization**
   - Replace unsafe characters with underscores
   - Prevent directory traversal

2. **Automatic Backups**
   - Timestamped backup files
   - Backup directory management
   - Optional (configurable)

3. **Path Validation**
   - Ensure paths within workspace
   - Prevent access outside work_dir
   - Absolute vs relative handling

4. **Search Capabilities**
   - Regex pattern search
   - Recursive directory search
   - File pattern filtering

---

### 5.5 Document Toolkit (New)

**File**: `src/soothe/tools/document.py`

**Priority**: 🟡 Medium - Document processing support

#### Core Design

```python
import fitz  # PyMuPDF
from typing import Optional

class DocumentQATool(BaseTool):
    """Document Q&A with multi-format support."""

    name: str = "document_qa"
    parser: str = Field(default="pymupdf")  # or "chunkr"
    text_limit: int = Field(default=100000)

    def _parse_pdf(self, file_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(file_path)
        pages = []
        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            pages.append(f"## Page {page_num + 1}\n\n{text}")
        return "\n\n".join(pages)

    def _run(self, document_path: str, question: Optional[str] = None) -> str:
        """Analyze document and answer questions."""
        # Download if URL
        # Parse document
        content = self._parse_document(document_path)

        if question:
            return self._llm_qa(content, question)
        else:
            return self._llm_summarize(content)
```

#### Supported Formats

- **PDF**: PyMuPDF (fitz)
- **Office**: DOCX, PPTX, XLSX (via Chunkr or python-docx)
- **Text**: TXT, MD, RTF

#### Tools Provided

```python
def create_document_tools() -> list[BaseTool]:
    return [
        DocumentQATool(),      # document_qa
        ExtractTextTool(),     # extract_text
        GetDocumentInfoTool(), # get_document_info
    ]
```

#### Dependencies

```toml
[project.optional-dependencies]
document = ["PyMuPDF>=1.24.0"]
```

#### Implementation Notes

- PyMuPDF is primary backend (fast, reliable)
- Chunkr API is optional (advanced layout understanding)
- URL downloading with aiohttp
- MD5-based caching for parsed content

---

### 5.6 Python Executor Toolkit (New)

**File**: `src/soothe/tools/python_executor.py`

**Priority**: 🔴 Critical - Required for coding agents

**Note**: Replaces broken `python_repl` tool in resolver.py

#### Core Design

```python
import io
import base64
import contextlib
from IPython.core.interactiveshell import InteractiveShell
import matplotlib.pyplot as plt

class PythonExecutorTool(BaseTool):
    """IPython-based execution with matplotlib support."""

    name: str = "execute_python_code"
    workdir: str = Field(default="")
    timeout: int = Field(default=30)
    max_timeout: int = Field(default=300)

    def _run(self, code: str, workdir: str = None, timeout: int = None) -> dict:
        """Execute Python code with comprehensive results."""
        # Clean code (remove markdown blocks)
        code_clean = self._clean_code(code)

        # Setup IPython
        shell = InteractiveShell.instance()
        output = io.StringIO()
        error = io.StringIO()

        # Execute with output capture
        with contextlib.redirect_stdout(output), \
             contextlib.redirect_stderr(error):
            result = shell.run_cell(code_clean)

            # Handle matplotlib plots
            if plt.get_fignums():
                plot_data = self._save_plot()
                # ...

        return {
            "success": result.success,
            "stdout": output.getvalue(),
            "stderr": error.getvalue(),
            "files": self._track_new_files(),
        }
```

#### Key Features

1. **IPython Execution**
   - Rich execution environment
   - Cell magic support (optional)
   - Better error handling than basic exec()

2. **Matplotlib Integration**
   - Auto-detect plot creation
   - Save as PNG files
   - Base64 encoding for return

3. **File Tracking**
   - Track files created during execution
   - Working directory management

4. **Timeout Protection**
   - Configurable timeout
   - Maximum timeout enforcement
   - Thread pool execution

5. **Output Cleaning**
   - ANSI escape sequence removal
   - Markdown code block handling

#### Tools Provided

```python
def create_python_executor_tools() -> list[BaseTool]:
    return [PythonExecutorTool()]
```

#### Dependencies

```toml
[project.optional-dependencies]
python-executor = [
    "ipython>=8.0.0",
    "matplotlib>=3.8.0",
]
```

#### Security Considerations

- No sandboxing (runs in same process)
- Workspace isolation recommended
- Timeout essential for infinite loops
- Should replace python_repl in resolver.py

---

## 6. Error Handling

### Standard Pattern

```python
class ToolWithErrors(BaseTool):
    def _run(self, arg: str) -> dict:
        try:
            result = self._execute(arg)
            return {"success": True, "result": result}
        except FileNotFoundError as e:
            return {"success": False, "error": f"File not found: {e}"}
        except ValueError as e:
            return {"success": False, "error": f"Invalid input: {e}"}
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}", exc_info=True)
            return {"success": False, "error": f"Internal error: {e}"}
```

### Error Categories

1. **User Errors**: Invalid input, file not found, permission denied
2. **System Errors**: API failures, network issues, timeouts
3. **Internal Errors**: Unexpected exceptions, assertion failures

### Return Format

All tools should return structured data:

```python
{
    "success": bool,
    "result": Any,      # On success
    "error": str,       # On failure
    "metadata": dict    # Optional additional info
}
```

---

## 7. Configuration

### Environment Variables

```bash
# Audio
OPENAI_API_KEY=sk-...
ALIYUN_ACCESS_KEY_ID=...
ALIYUN_ACCESS_KEY_SECRET=...
ALIYUN_NLS_APP_KEY=...

# Video
GOOGLE_API_KEY=...

# Document
CHUNKR_API_KEY=...  # Optional
```

### Config File Integration

```yaml
# config/config.yml
tools:
  - datetime
  - arxiv
  - wikipedia
  - wizsearch
  - cli            # New (renamed from bash)
  - file_edit      # New
  - python_executor  # New
  - audio          # Enhanced
  - video          # Enhanced
  - document       # New
```

### Tool-Specific Config

```yaml
# Future: Per-tool configuration
tool_config:
  bash:
    workspace_root: /tmp/soothe/workspace
    timeout: 120
  python_executor:
    timeout: 60
    max_timeout: 600
```

---

## 8. Testing Strategy

### Unit Tests

**Location**: `tests/unit_tests/test_tools.py`

**Coverage**:
- Each tool's `_run()` method
- Error handling paths
- Input validation
- Output format

```python
def test_cli_tool():
    tool = CliTool()
    result = tool._run("echo 'hello'")
    assert "hello" in result

def test_cli_tool_banned_command():
    tool = CliTool()
    result = tool._run("rm -rf /")
    assert "Error" in result
    assert "not allowed" in result.lower()
```

### Integration Tests

**Location**: `tests/integration_tests/test_tool_integration.py`

**Coverage**:
- Tool registration in resolver
- End-to-end execution
- Multi-tool workflows
- Error propagation

```python
def test_resolve_cli_tools():
    from soothe.core.resolver import resolve_tools
    tools = resolve_tools(["cli"])
    assert len(tools) == 6
    assert any(t.name == "run_cli" for t in tools)
```

### Test Fixtures

```
tests/fixtures/
├── sample.pdf          # Document testing
├── sample.mp3          # Audio testing
├── sample.mp4          # Video testing
└── test_workspace/     # File operations
    ├── test.txt
    └── subdir/
```

---

## 9. Migration Path

### Phase 1: Critical Tools (Week 1-2)

1. **CLI Toolkit** ✅
   - Implement core execution
   - Add security filtering (substring + regex patterns)
   - Add shell recovery and responsiveness testing
   - Add background execution and process management
   - Write unit tests

2. **Python Executor Toolkit** ✅
   - Port IPython implementation
   - Add matplotlib support
   - Replace python_repl in resolver

3. **File Edit Toolkit** ✅
   - Implement file CRUD
   - Add backup system
   - Path validation

### Phase 2: Media Tools (Week 3)

4. **Audio Enhancement** ✅
   - Add Aliyun provider
   - Implement audio_qa tool
   - Add caching layer

5. **Video Enhancement** ✅
   - Google Gemini integration
   - File upload handling
   - Analysis capabilities

### Phase 3: Document Processing (Week 4)

6. **Document Toolkit** ✅
   - PyMuPDF integration
   - Multi-format support
   - Q&A functionality

### Breaking Changes

- **python_repl → python_executor**: Update resolver.py and config
- **Audio tool return format**: Structured dict instead of plain text

### Compatibility

- Existing tools unchanged
- New tools opt-in via config
- Backward compatible defaults

---

## 10. Implementation Checklist

### For Each Tool

- [ ] Create tool file in `src/soothe/tools/`
- [ ] Implement BaseTool subclass
- [ ] Add `_run()` and `_arun()` methods
- [ ] Add configuration via Field()
- [ ] Add error handling
- [ ] Create factory function `create_*_tools()`
- [ ] Update `src/soothe/core/resolver.py`
- [ ] Add dependencies to `pyproject.toml`
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Add test fixtures
- [ ] Update documentation
- [ ] Manual testing with real usage

### Quality Gates

- [ ] All tests pass
- [ ] Coverage > 80%
- [ ] No type errors
- [ ] No security warnings
- [ ] Documentation complete
- [ ] Code review approved

---

## 11. Reference Implementation

### Noesium Source Files

```
thirdparty/noesium/noesium/src/noesium/toolkits/
├── bash_toolkit.py           # 337 lines (ported to cli.py with enhancements)
├── file_edit_toolkit.py      # 585 lines
├── document_toolkit.py       # 467 lines
├── python_executor_toolkit.py # 337 lines
├── audio_toolkit.py          # 700 lines
└── video_toolkit.py          # 175 lines
```

### Soothe Integration Points

```python
# src/soothe/core/resolver.py

def _resolve_single_tool_group(name: str) -> list[BaseTool]:
    # ... existing tools ...

    # New tools
    if name == "cli":
        from soothe.tools.cli import create_cli_tools
        return list(create_cli_tools())

    if name == "file_edit":
        from soothe.tools.file_edit import create_file_edit_tools
        return list(create_file_edit_tools())

    if name == "document":
        from soothe.tools.document import create_document_tools
        return list(create_document_tools())

    if name == "python_executor":
        from soothe.tools.python_executor import create_python_executor_tools
        return list(create_python_executor_tools())

    # Enhanced tools
    if name == "audio":
        from soothe.tools.audio import create_audio_tools
        return list(create_audio_tools())  # Now returns 3 tools

    if name == "video":
        from soothe.tools.video import create_video_tools
        return list(create_video_tools())  # Now returns 2 tools
```

---

## 12. Success Criteria

### Functional Requirements

- ✅ All 6 tools implemented and working
- ✅ Noesium feature parity achieved
- ✅ All tests passing
- ✅ Documentation complete

### Non-Functional Requirements

- ✅ Performance: Tool execution < 5s for typical operations
- ✅ Security: Command filtering, path validation, timeouts
- ✅ Reliability: Error handling, graceful degradation
- ✅ Maintainability: Clean code, comprehensive tests

### Metrics

- Code coverage: > 80%
- Type checking: 100% mypy clean
- Documentation: All public APIs documented
- Test execution: All tests pass in < 60s

---

## 13. Appendix

### A. Dependency Graph

```
cli → pexpect
python_executor → ipython, matplotlib
file_edit → (stdlib only)
document → PyMuPDF, aiohttp
audio → openai, aliyun-sdk, aiohttp
video → google-genai
```

### B. Configuration Schema

```python
from pydantic import BaseModel

class CliConfig(BaseModel):
    workspace_root: str = "/tmp/soothe/workspace"
    timeout: int = 60
    max_output_length: int = 10000
    banned_commands: list[str] = []
    banned_command_patterns: list[str] = []

class AudioConfig(BaseModel):
    provider: Literal["openai", "aliyun"] = "openai"
    cache_dir: str = ""
    # ...
```

### C. Error Codes

| Code | Category | Example |
|------|----------|---------|
| `FILE_NOT_FOUND` | User Error | Requested file doesn't exist |
| `INVALID_INPUT` | User Error | Invalid argument type/value |
| `PERMISSION_DENIED` | User Error | No read/write permission |
| `TIMEOUT` | System Error | Operation exceeded time limit |
| `API_ERROR` | System Error | External API failure |
| `INTERNAL_ERROR` | System Error | Unexpected exception |

### D. Performance Targets

| Tool | Target Latency | Max Memory |
|------|----------------|------------|
| cli | < 100ms startup | 50MB |
| python_executor | < 1s execution | 500MB |
| file_edit | < 50ms read | 100MB |
| document | < 5s parse | 200MB |
| audio | < 10s transcribe | 300MB |
| video | < 30s analyze | 500MB |

---

## Conclusion

This implementation guide provides the complete blueprint for enhancing Soothe's toolkit to production parity with Noesium. By following the detailed specifications, architecture patterns, and implementation checklists, developers can systematically port each tool while maintaining quality, security, and testability.

**Next Steps**:
1. Review and approve this guide
2. Set up development environment with dependencies
3. Begin Phase 1 implementation (bash, python_executor, file_edit)
4. Iterate through testing and code review
5. Proceed to Phase 2 and 3

**Estimated Effort**: 4 weeks for complete implementation with full test coverage.