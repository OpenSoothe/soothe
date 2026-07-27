"""System prompt templates for Soothe agents (CoreAgent defaults and tool guides).

Moved from ``soothe.config.prompts`` (IG-384); imported by config package for re-exports.

Static prose lives as ``.xml`` fragments under ``soothe.prompts.fragments``.
CoreAgent defaults also live in ``soothe_nano.prompts``; this host module
composes loop-facing templates. Goal-completion report layout is owned by
``instructions/synthesis_report_system.xml`` (IG-652), not legacy response guides.
"""

from __future__ import annotations

# Re-export facade — canonical source: soothe_nano.prompts.system_templates
# (nano owns the shared guide strings; host overrides are marked [HOST OVERRIDES])
from soothe_nano.prompts.system_templates import (
    _DATA_GUIDE,
    _FILE_OPS_GUIDE,
    _RESPONSE_LANGUAGE_DISPLAY,
    _SURGICAL_EDIT_GUIDE,
    RESPONSE_LANGUAGE_HINT_FALLBACK,
)

from soothe.prompts.fragments import (
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

# [HOST OVERRIDES] — nano's _SHELL_GUIDE is generic; this override adds
# Soothe daemon-safety rules (never kill soothed / :8765 / pkill soothe) and
# integration-test guidance (ephemeral ports, never bind :8765).
_SHELL_GUIDE = """\
Execution tools (always bound — not listed in <AVAILABLE_TOOLS>):
- run_command: Sync shell — waits for completion and returns output. Default timeout 60s; pass timeout for longer bounded jobs (max 5h, e.g. timeout=3600). Use for: ls, curl, git, make test, one-shot scripts.
- run_background: Async shell — returns PID + log_path immediately. Use for: servers, daemons, training, long builds you poll separately. Follow with tail_background_log/read_file; stop with kill_process.
- run_python: Execute Python code with session persistence. Variables persist across calls.
- tail_background_log: Read the last N lines from a run_background log (bg-{{pid}}.log).
- kill_process: Terminate a run_background PID only (the pid field returned at spawn). Never kill soothed, the live daemon on :8765, or PIDs from `ps | grep soothe`. Never use pkill/killall/soothed stop against the host daemon from these tools.

Choose run_command vs run_background:
- Need output/exit code in this step → run_command (set timeout if >60s).
- Process keeps running after spawn (HTTP server, nohup job) → run_background.
- Unsure duration but must block until done → run_command with generous timeout.
- Integration tests for soothe-daemon: use ephemeral ports from fixtures — never bind or target host :8765.
"""

# [HOST OVERRIDES] — nano's _RESEARCH_GUIDE suggests "dedicated research tools
# or specialists"; this override documents Soothe intake/slash routing
# (deep_research / academic_research are not open via `task`).
_RESEARCH_GUIDE = """\
Research tools (deferred by default — see <AVAILABLE_TOOLS> or search_tools):
- search_web: Quick web search for factual lookups, news, current events (single call).
- crawl_web: Extract clean content from a web page URL.
Thorough multi-source public-web or academic research is intake/slash routed
(deep_research / academic_research) — those specialists are not available via `task`.\
"""

# [HOST OVERRIDES] — nano's _SUBAGENT_GUIDE is generic; this override reflects
# Soothe's intake/slash routing for browser_use, deep_research, and
# academic_research (not available via open `task`), and adds a grep/glob
# guard against redundant repo scans after a task report returns.
_SUBAGENT_GUIDE = """\
Subagents (via the `task` tool) -- delegate ONLY when the task requires \
the subagent's unique capability:
- planner: Agentic plan design — iterative markdown execution plan; one report.
- browser_use, deep_research, and academic_research are not available via `task`; \
they run only through intake/slash wired routing.
Additional subagents may be available from installed plugins; use only names listed in your runtime capabilities.

Do NOT use `task` for mechanical multi-pattern repo search, file enumeration, \
or reference confirmation — use batched `grep` / one `run_command` with `rg` instead. \
Use `task` only for multi-hop reasoning the parent tools cannot finish in one wave. \
After a `task` report returns, treat it as evidence: do not re-grep the same \
symbols/paths; only spot-check disputed hits.\
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
- Use websearch/crawl_web for lookups; thorough public-web or academic research is intake-routed (not open `task`).
- Use run_command for sync shell (pass timeout when the job may exceed 60s); use run_background for servers/daemons and jobs you poll via tail_background_log; kill_process stops only run_background PIDs (never soothed / :8765 / pkill soothe); run_python for Python code.
- When you need a deferred tool (data, wizsearch, HTTP, etc.), check <AVAILABLE_TOOLS> or run search_tools first.\
"""


def build_response_language_hint(language: object | None) -> str:
    """Build explicit or fallback ``RESPONSE_LANGUAGE_HINT`` for system prompts.

    Args:
        language: ``ResponseLanguage`` or wire string (``en``, ``zh``, etc.).

    Returns:
        XML fragment instructing the model which language to use for user-facing prose.
    """
    from soothe.sloop.intention.models import (
        ResponseLanguage,
        normalize_response_language,
    )

    resolved = normalize_response_language(language)
    if resolved is None or resolved == ResponseLanguage.OTHER:
        return RESPONSE_LANGUAGE_HINT_FALLBACK
    display = _RESPONSE_LANGUAGE_DISPLAY.get(resolved.value, resolved.value)
    return (
        f"<RESPONSE_LANGUAGE_HINT>\n"
        f"Write all user-facing prose in {display} ({resolved.value}). "
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
    from soothe.utils.prompt_clock import local_timestamp_iso

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
