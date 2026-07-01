"""System prompt templates for Soothe agents (CoreAgent defaults and tool guides).

Moved from ``soothe.config.prompts`` (IG-384); imported by config package for re-exports.

Static prose (system prompts and scenario response guides) lives as ``.xml``
fragments under ``soothe.core.prompts.fragments``; this module composes them
with the in-process tool/subagent guides into the final templates.
"""

from __future__ import annotations

from soothe.foundation.sloop.prompts.fragments import (
    ARCHITECTURE_ANALYSIS_GUIDE_FRAGMENT,
    DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT,
    LOOP_CONTINUATION_GUIDE_FRAGMENT,
    MEDIUM_SYSTEM_PROMPT_FRAGMENT,
    QUIZ_RESPONSE_GUIDE_FRAGMENT,
    RESEARCH_SYNTHESIS_GUIDE_FRAGMENT,
    SIMPLE_SYSTEM_PROMPT_FRAGMENT,
)

# ---------------------------------------------------------------------------
# Scenario-specific guides (IG-268: Intelligent response length control)
# Sourced from prompts/fragments/system/response_guides/*.xml.
# ---------------------------------------------------------------------------

_ARCHITECTURE_ANALYSIS_GUIDE = ARCHITECTURE_ANALYSIS_GUIDE_FRAGMENT
_RESEARCH_SYNTHESIS_GUIDE = RESEARCH_SYNTHESIS_GUIDE_FRAGMENT
_LOOP_CONTINUATION_GUIDE = LOOP_CONTINUATION_GUIDE_FRAGMENT
_QUIZ_RESPONSE_GUIDE = QUIZ_RESPONSE_GUIDE_FRAGMENT

# ---------------------------------------------------------------------------
# Domain-scoped tool guides (RFC-0016)
# Updated to use single-purpose tools instead of unified dispatch tools.
# Tool/subagent guides stay inline so tool surface changes ship in the same
# module as the runtime tool registration.
# ---------------------------------------------------------------------------

_SHELL_GUIDE = """\
Execution tools (always bound — not listed in <AVAILABLE_TOOLS>):
- run_command: Execute shell commands synchronously (returns output). Use for: CLI tools, scripts.
- run_python: Execute Python code with session persistence. Variables persist across calls.
- run_background: Run long commands in background (returns PID). Use for: training, servers, builds.
- kill_process: Terminate background process by PID from run_background.
"""

_FILE_OPS_GUIDE = """\
File operation tools:
- read_file: Read file contents (optional start_line, end_line for ranges).
- write_file: Write to files (mode='overwrite' or 'append').
- delete_file: Delete files (automatic backups created).
- search_files: Search for pattern in files (grep-like).
- list_files: List files matching pattern.
- file_info: Get file metadata.
"""

_SURGICAL_EDIT_GUIDE = """\
Surgical editing tools (PREFERRED over full-file rewrites):
- edit_file_lines: Replace specific line range (safer than read→modify→write).
- insert_lines: Insert content at specific line.
- delete_lines: Delete specific line range.
- apply_diff: Apply unified diff patch.

When to use surgical editing:
- Changing a specific function → use edit_file_lines
- Adding imports → use insert_lines at line 1
- Removing unused code → use delete_lines
- Applying code review patches → use apply_diff

Benefits:
- Safer: Only touch the lines you need to change
- Faster: No need to read/write entire large files
- Clearer: Changes are scoped and precise
"""

_RESEARCH_GUIDE = """\
Research tools (deferred by default — see <AVAILABLE_TOOLS> or search_tools):
- search_web: Quick web search for factual lookups, news, current events (single call).
- crawl_web: Extract clean content from a web page URL.
- tacitus: Public-domain deep investigation (web, academic, URLs).
  Set domain='web' for internet, 'code' for codebase, 'deep' for all, 'auto' to decide.\
"""

_DATA_GUIDE = """\
Data inspection tools (deferred by default — see <AVAILABLE_TOOLS> or search_tools):
- inspect_data: Inspect data file structure - columns, types, samples (CSV, Excel, JSON, Parquet).
- summarize_data: Get statistical summary of data (tabular) or document summary (PDF, DOCX).
- check_data_quality: Validate data quality - missing values, duplicates, anomalies (tabular only).
- extract_text: Extract raw text from documents (PDF, DOCX, TXT, MD).
- get_data_info: Get file metadata - size, format, page count, modification time.
- ask_about_file: Answer questions about file content (documents use AI, tabular shows schema).\
"""

_SUBAGENT_GUIDE = """\
Subagents (via the `task` tool) -- delegate ONLY when the task requires \
the subagent's unique capability:
- explore: Readonly repo search (glob/grep/list/read); locate/map/trace; not edits or shell.
- plan: Agentic recon then plan — multiple explore batches/rounds, then iterative markdown plan; one report.
- tacitus: Web or multi-source public-domain investigation—not trivial directory walks.
Additional subagents may be available from installed plugins; use only names listed in your runtime capabilities.\
"""

_TOOL_ORCHESTRATION_GUIDE = f"""\

Tool selection rules (follow strictly):

{_SHELL_GUIDE}

{_FILE_OPS_GUIDE}

{_SURGICAL_EDIT_GUIDE}

{_DATA_GUIDE}

{_RESEARCH_GUIDE}

- datetime: Get current date and time.

{_SUBAGENT_GUIDE}

Progressive tool binding:
- Always bound: filesystem, surgical edits, execution (run_command, run_python, run_background, kill_process), search_tools, write_todos, task, current_datetime.
- <AVAILABLE_TOOLS> lists deferred tools not yet bound to this hop. Use search_tools(query) or call a listed name to promote it for subsequent hops.

Key rules:
- Prefer single-purpose tools over unified dispatch tools.
- Use surgical editing (edit_file_lines) instead of full-file rewrites.
- Use websearch for quick lookups; use tacitus for thorough public-domain investigation.
- Use run_command for sync shell, run_background for long-running jobs, kill_process to stop background PIDs, run_python for Python code.
- When you need a deferred tool (data, wizsearch, HTTP, etc.), check <AVAILABLE_TOOLS> or run search_tools first.\
"""

# Cache-stable directive about user-facing prose language. Lives in the system
# prompt so the per-turn user envelope stays small and the directive is recorded
# once in the prefix.
RESPONSE_LANGUAGE_HINT_FRAGMENT = (
    "<RESPONSE_LANGUAGE_HINT>\n"
    "Prefer the same natural language as the user's goal for explanations, "
    "summaries, and conclusions; keep code, file paths, identifiers, and "
    "quoted literals unchanged.\n"
    "</RESPONSE_LANGUAGE_HINT>"
)


def current_timestamp_iso() -> str:
    """Return current local-timezone ISO-8601 timestamp for system prompts."""
    import datetime as dt

    return dt.datetime.now(dt.UTC).astimezone().isoformat()


def build_timestamp_xml_footer() -> str:
    """Append volatile clock to system prompts (bottom-right XML tag).

    User/ledger messages must not carry timestamps — they break prompt-cache
    prefixes when replayed from the RFC-214 ledger.
    """
    return f"<TIMESTAMP>\n{current_timestamp_iso()}\n</TIMESTAMP>"


_DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT + _TOOL_ORCHESTRATION_GUIDE

_SIMPLE_SYSTEM_PROMPT = SIMPLE_SYSTEM_PROMPT_FRAGMENT

_MEDIUM_SYSTEM_PROMPT = MEDIUM_SYSTEM_PROMPT_FRAGMENT
