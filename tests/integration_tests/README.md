# Integration Tests

This directory contains integration tests that require external services and real LLM invocations.

## Structure

```
integration_tests/
├── conftest.py                        # Shared fixtures and pytest configuration
├── test_file_ops_tools.py             # File operations tools (read, write, delete, search, list, info)
├── test_code_edit_tools.py            # Code editing tools (edit lines, insert, delete)
├── test_execution_tools.py            # Execution tools (shell commands, Python execution)
├── test_multimedia_tools.py           # Audio, image, video tools
├── test_web_tools.py                  # Web search, crawl, research tools
├── test_data_tools.py                 # Data/document inspection and analysis
├── test_vector_store_integration.py   # Vector store backends (PGVector, Weaviate)
├── test_python_session_integration.py # Python session persistence
├── test_system_prompt_optimization.py # System prompt optimization
├── test_performance.py                # Performance optimizations
├── test_http_rest_transport.py        # HTTP REST transport
└── test_multi_transport.py            # WebSocket transport
```

**Total Tests: 144** across 12 test modules

## Running Tests

Integration tests are marked with `@pytest.mark.integration` and require the `--run-integration` flag:

```bash
# Run all integration tests
pytest tests/integration_tests --run-integration

# Run specific test file
pytest tests/integration_tests/test_tools_integration.py --run-integration

# Run with verbose output
pytest tests/integration_tests --run-integration -v
```

## Requirements

### Environment Variables

- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: Required for LLM-based tests
- `POSTGRES_DSN`: Optional, for PGVector tests (default: `postgresql://postgres:postgres@localhost:5432/vectordb`)
- `WEAVIATE_URL`: Optional, for Weaviate tests (default: `http://localhost:8081`)

### External Services

Some tests require running external services:

- **PostgreSQL with pgvector**: For vector store integration tests
- **Weaviate**: For vector store integration tests (optional)

## Test Categories

### 1. File Operations Tools Tests (`test_file_ops_tools.py`)

**23 tests** for file operation tools from `soothe.tools.file_ops`:

- **ReadFileTool**: Basic reading, line ranges, large files, binary files, error handling
- **WriteFileTool**: Create files, overwrite, nested directories, Unicode content
- **DeleteFileTool**: Delete existing and non-existent files
- **SearchFilesTool**: Pattern matching, recursive search
- **ListFilesTool**: Directory listing, empty directories
- **FileInfoTool**: File metadata retrieval
- **Error Handling**: Permission errors, disk full, concurrent access

### 2. Code Editing Tools Tests (`test_code_edit_tools.py`)

**15 tests** for code editing tools from `soothe.tools.code_edit`:

- **EditFileLinesTool**: Single/multi-line editing, invalid line numbers, indentation preservation
- **InsertLinesTool**: Insert at position, beginning, multiple lines, content preservation
- **DeleteLinesTool**: Line range deletion, single line, end of file, invalid line numbers
- **Error Handling**: Non-existent files, read-only files, locked files

### 3. Execution Tools Tests (`test_execution_tools.py`)

**21 tests** for execution tools from `soothe.tools.execution`:

- **RunCommandTool**: Simple commands, exit codes, pipes, timeouts, arguments, environment variables, redirection
- **RunPythonTool**: Calculations, variable/import persistence, error handling, session isolation, matplotlib, pandas, multiline code, syntax errors
- **Error Handling**: Shell injection, memory limits, timeouts, concurrent sessions

### 4. Multimedia Tools Tests (`test_multimedia_tools.py`)

**11 tests** for multimedia processing tools:

- **Audio Tools**: transcription, caching, format validation
- **Image Tools**: analysis, base64 conversion, resizing, URL handling
- **Video Tools**: analysis, file validation, API key handling
- **Error Handling**: invalid formats, corrupted files, missing API keys

### 5. Web Tools Tests (`test_web_tools.py`)

**14 tests** for web-related tools:

- **Web Search**: basic search, backend selection, max results, error handling
- **Web Crawl**: content extraction, backend selection, URL validation, timeouts
- **Research**: deep investigation, multi-source aggregation
- **Error Handling**: rate limiting, authentication, large pages

### 6. Data Tools Tests (`test_data_tools.py`)

**17 tests** for data/document inspection and analysis:

- **Data Inspection**: CSV, JSON, Parquet, Excel file structure analysis
- **Data Summary**: statistical summaries, numeric and categorical data
- **Data Quality**: missing values, duplicate detection
- **Document Extraction**: PDF, DOCX, TXT, Markdown text extraction
- **Document Q&A**: content-based question answering
- **File Info**: metadata extraction

### 7. Vector Store Tests (`test_vector_store_integration.py`)

**18 tests** for vector store backends:

- PGVector (PostgreSQL with pgvector extension)
- Weaviate

### 8. Python Session Tests (`test_python_session_integration.py`)

**10 tests** for Python execution session persistence:

- Variable persistence across calls
- Import persistence and isolation
- Session cleanup and management
- Error recovery

### 9. Performance Tests (`test_performance.py`)

**7 tests** for performance optimization features:

- Query complexity classification
- Template planning
- Conditional memory recall and context projection
- Parallel execution
- Feature flags

### 10. System Prompt Optimization Tests (`test_system_prompt_optimization.py`)

**2 tests** for system prompt optimization feature:

- Enabled state verification
- Disabled state verification

### 11. HTTP REST Transport Tests (`test_http_rest_transport.py`)

**5 tests** for HTTP REST transport:

- Basic lifecycle
- Health endpoint
- Status endpoint
- Version endpoint
- OpenAPI documentation endpoints

### 12. WebSocket Transport Tests (`test_multi_transport.py`)

**3 tests** for WebSocket transport:

- Basic lifecycle
- Client connection
- Broadcast functionality

## Tool Coverage by Module

Tests are organized to match `src/soothe/tools/` module structure:

### soothe.tools.file_ops
- `read_file`: Read file contents with optional line ranges
- `write_file`: Write content to files (create/overwrite)
- `delete_file`: Delete files
- `search_files`: Search files by pattern
- `list_files`: List directory contents
- `file_info`: Get file metadata

### soothe.tools.code_edit
- `edit_file_lines`: Surgical line-based editing
- `insert_lines`: Insert lines at specific positions
- `delete_lines`: Delete specific line ranges

### soothe.tools.execution
- `run_command`: Execute shell commands
- `run_python`: Execute Python code with session persistence

### soothe.tools.web_search
- `search_web`: Unified web search with backend selection
- `crawl_web`: Content extraction with backend selection

### soothe.tools.research
- `research`: Deep multi-source investigation

### soothe.tools.audio
- `transcribe_audio`: Audio transcription (OpenAI Whisper)

### soothe.tools.image
- `analyze_image`: Image analysis (Vision models)

### soothe.tools.video
- `analyze_video`: Video analysis (Google Gemini)

### soothe.tools.data
- `inspect_data`: Inspect data file structure
- `summarize_data`: Get statistical summary
- `check_data_quality`: Validate data quality
- `extract_text`: Extract text from documents
- `get_data_info`: Get file metadata
- `ask_about_file`: Q&A on file content

**2 tests** for system prompt optimization feature:

- Enabled state verification
- Disabled state verification

### 9. HTTP REST Transport Tests (`test_http_rest_transport.py`)

**5 tests** for HTTP REST transport:

- Basic lifecycle
- Health endpoint
- Status endpoint
- Version endpoint
- OpenAPI documentation endpoints

### 10. WebSocket Transport Tests (`test_multi_transport.py`)

**3 tests** for WebSocket transport:

- Basic lifecycle
- Client connection
- Broadcast functionality

## Tool Coverage

The integration tests cover the following Soothe tools:

### File Operations (file_ops.py)
- `read_file`: Read file contents with optional line ranges
- `write_file`: Write content to files (create/overwrite)
- `delete_file`: Delete files
- `search_files`: Search files by pattern
- `list_files`: List directory contents
- `file_info`: Get file metadata

### Code Editing (code_edit.py)
- `edit_file_lines`: Surgical line-based editing
- `insert_lines`: Insert lines at specific positions
- `delete_lines`: Delete specific line ranges

### Execution (execution.py)
- `run_command`: Execute shell commands
- `run_python`: Execute Python code with session persistence

### Web Search (web_search.py)
- `search_web`: Unified web search with backend selection
- `crawl_web`: Content extraction with backend selection

### Research (research.py)
- `research`: Deep multi-source investigation

### Multimedia
- Audio: `transcribe_audio` (OpenAI Whisper)
- Image: `analyze_image` (Vision models)
- Video: `analyze_video` (Google Gemini)

### Data/Document Analysis (data.py)
- `inspect_data`: Inspect data file structure
- `summarize_data`: Get statistical summary
- `check_data_quality`: Validate data quality
- `extract_text`: Extract text from documents
- `get_data_info`: Get file metadata
- `ask_about_file`: Q&A on file content

## Running Tests

Integration tests are marked with `@pytest.mark.integration` and require the `--run-integration` flag:

```bash
# Run all integration tests
pytest tests/integration_tests --run-integration

# Run specific test category
pytest tests/integration_tests/test_tools_integration.py --run-integration

# Run specific test class
pytest tests/integration_tests/test_tools_integration.py::TestFileReadTools --run-integration

# Run with verbose output
pytest tests/integration_tests --run-integration -v

# Run with coverage
pytest tests/integration_tests --run-integration --cov=soothe --cov-report=html
```