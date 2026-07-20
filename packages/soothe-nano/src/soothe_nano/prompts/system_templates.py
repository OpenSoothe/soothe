"""System prompt templates for Coding CoreAgent (defaults and tool guides).

Static system prompt bodies live as ``.xml`` fragments under
``soothe_nano.prompts.fragments``; this module composes them with the
in-process tool/subagent guides into the final templates.

Host loop plan/classifier templates live under ``soothe.prompts``.
"""

from __future__ import annotations

from soothe_nano.prompts.fragments import (
    DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT,
    MEDIUM_SYSTEM_PROMPT_FRAGMENT,
    SIMPLE_SYSTEM_PROMPT_FRAGMENT,
)

# ---------------------------------------------------------------------------
# Domain-scoped tool guides (RFC-0016)
# Updated to use single-purpose tools instead of unified dispatch tools.
# Tool/subagent guides stay inline so tool surface changes ship in the same
# module as the runtime tool registration.
# ---------------------------------------------------------------------------

_SHELL_GUIDE = """\
Execution tools (always bound — not listed in <AVAILABLE_TOOLS>):
- run_command: Sync shell — waits for completion and returns output. Default timeout 60s; pass timeout for longer bounded jobs (max 5h, e.g. timeout=3600). Use for: ls, curl, git, make test, one-shot scripts.
- run_background: Async shell — returns PID + log_path immediately. Use for: servers, daemons, training, long builds you poll separately. Follow with tail_background_log/read_file; stop with kill_process.
- run_python: Execute Python code with session persistence. Variables persist across calls.
- tail_background_log: Read the last N lines from a run_background log (bg-{{pid}}.log).
- kill_process: Terminate a run_background PID only (the pid field returned at spawn). Never kill the agent host process or use pkill/killall against the runtime that spawned you.

Choose run_command vs run_background:
- Need output/exit code in this step → run_command (set timeout if >60s).
- Process keeps running after spawn (HTTP server, nohup job) → run_background.
- Unsure duration but must block until done → run_command with generous timeout.
"""

_FILE_OPS_GUIDE = """\
File operation tools:
- read_file: Read file contents (optional start_line, end_line for ranges).
- write_file: Write to files (mode='overwrite' or 'append').
- delete: Delete files (use backup=true to create automatic backup).
- search_files: Search for pattern in files (grep-like).
- list_files: List files matching pattern.
- file_info: Get file metadata.
"""

_SURGICAL_EDIT_GUIDE = """\
Surgical editing tools (PREFERRED over full-file rewrites):
- edit_lines: Replace specific line range (safer than read→modify→write).
- insert_lines: Insert content at specific line.
- delete_lines: Delete specific line range.
- apply_diff: Apply unified diff patch.

When to use surgical editing:
- Changing a specific function → use edit_lines
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
For deeper multi-source research, prefer dedicated research tools or specialists listed in your runtime capabilities.\
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
- planner: Agentic plan design — iterative markdown execution plan; one report.
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
- Always bound: filesystem, surgical edits, execution (run_command, run_python, run_background, tail_background_log, kill_process), search_tools, search_skills, invoke_skill, write_todos, task, current_datetime.
- <AVAILABLE_TOOLS> lists deferred tools not yet bound to this hop. Use search_tools(query) or call a listed name to promote it for subsequent hops.
- Core/builtin skills appear in <AVAILABLE_SKILLS> on turn 0. Matching skills auto-load into <SKILL_CONTEXT> — follow those instructions before search_tools or ad-hoc web research.
- Deferred skills stay hidden until search_skills(query), invoke_skill(name), or a matching file-op path auto-discovers them.
- search_skills discovers deferred skills only. For core skills listed in <AVAILABLE_SKILLS>, use invoke_skill(name) or rely on auto-loaded <SKILL_CONTEXT>.

Key rules:
- Prefer single-purpose tools over unified dispatch tools.
- Use surgical editing (edit_lines) instead of full-file rewrites.
- Use websearch/crawl_web for lookups; use listed specialists for deeper research when available.
- Use run_command for sync shell (pass timeout when the job may exceed 60s); use run_background for servers/daemons and jobs you poll via tail_background_log; kill_process stops only run_background PIDs; run_python for Python code.
- When you need a deferred tool (data, wizsearch, HTTP, etc.), check <AVAILABLE_TOOLS> or run search_tools first.\
"""

SKILL_CONTEXT_ACTIVE_GUIDE = (
    "<SKILL_CONTEXT_GUIDE>\n"
    "One or more skills are pre-loaded in <SKILL_CONTEXT> below. Follow their "
    "instructions on this hop before any other discovery path.\n"
    "Use run_command or run_python exactly as the skill documents. Do NOT call "
    "search_tools, search_skills, task, deep_research, or browser_use for work the "
    "loaded skill already covers.\n"
    "For simple lookups, one compact command is usually enough — avoid a second "
    "full JSON fetch unless the user asked for detailed data.\n"
    "</SKILL_CONTEXT_GUIDE>"
)

# Cache-stable fallback when response language is unknown (fail-safe).
RESPONSE_LANGUAGE_HINT_FALLBACK = (
    "<RESPONSE_LANGUAGE_HINT>\n"
    "Prefer the same natural language as the user's goal for explanations, "
    "summaries, and conclusions; keep code, file paths, identifiers, and "
    "quoted literals unchanged.\n"
    "</RESPONSE_LANGUAGE_HINT>"
)

_RESPONSE_LANGUAGE_DISPLAY: dict[str, str] = {
    "en": "English",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}


def build_response_language_hint(language: object | None) -> str:
    """Build explicit or fallback ``RESPONSE_LANGUAGE_HINT`` for system prompts."""
    if language is None:
        return RESPONSE_LANGUAGE_HINT_FALLBACK
    text = str(language).strip().lower()
    if not text or text == "other":
        return RESPONSE_LANGUAGE_HINT_FALLBACK
    display = _RESPONSE_LANGUAGE_DISPLAY.get(text, text)
    return (
        f"<RESPONSE_LANGUAGE_HINT>\n"
        f"Write all user-facing prose in {display} ({text}). "
        f"Keep code, file paths, identifiers, and quoted literals unchanged.\n"
        f"</RESPONSE_LANGUAGE_HINT>"
    )


# Execute-step workspace path semantics (RFC-214 cache-stable tail).
EXECUTE_WORKSPACE_RULES_FRAGMENT = (
    "<WORKSPACE_RULES>\n"
    "Project root is under <WORKSPACE><root>. Filesystem tools: workspace-relative "
    "or host-absolute paths under that root. Shell tools (run_command, run_python): "
    "cwd = workspace root; leading '/' in shell = host root — use '.' or relative paths.\n\n"
    "For architecture/codebase/structure goals: inspect this directory immediately.\n"
    "Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal "
    "names a different project outside this directory.\n"
    "Do NOT tell the user you need them to share the project first — it is already here.\n"
    "</WORKSPACE_RULES>"
)


def current_timestamp_iso() -> str:
    """Return current local-timezone ISO-8601 timestamp for system prompts."""
    from soothe_nano.utils.prompt_clock import local_timestamp_iso

    return local_timestamp_iso()


def build_timestamp_xml_footer() -> str:
    """Append volatile clock to system prompts (bottom-right XML tag).

    User/ledger messages must not carry timestamps — they break prompt-cache
    prefixes when replayed from the RFC-214 ledger.
    """
    return f"<TIMESTAMP>\n{current_timestamp_iso()}\n</TIMESTAMP>"


_DEFAULT_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT + _TOOL_ORCHESTRATION_GUIDE


def default_agent_system_prompt_body() -> str:
    """Return the configurable identity/behavior body (tool guide appended at runtime when builtin)."""
    return DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT


def uses_builtin_agent_system_prompt(system_prompt: str | None) -> bool:
    """True when YAML/config should resolve to the built-in default (body + tool guide)."""
    if not system_prompt:
        return True
    return system_prompt.strip() == DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT.strip()


def format_complex_agent_system_prompt_core(system_prompt: str | None, assistant_name: str) -> str:
    """Format the complex-tier behavioral core (includes tool guide for builtin default)."""
    if uses_builtin_agent_system_prompt(system_prompt):
        return _DEFAULT_SYSTEM_PROMPT.format(assistant_name=assistant_name)
    return system_prompt.format(assistant_name=assistant_name)


_SIMPLE_SYSTEM_PROMPT = SIMPLE_SYSTEM_PROMPT_FRAGMENT

_MEDIUM_SYSTEM_PROMPT = MEDIUM_SYSTEM_PROMPT_FRAGMENT
