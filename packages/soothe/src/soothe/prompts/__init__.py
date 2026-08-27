"""Host prompt construction.

Nano-owned CoreAgent templates, identity, context XML, and project-instruction
helpers are re-exported here, along with do-or-decompose THREAD copy from
``fragments/decompose/``. Other StrangeLoop envelopes, ledger projection, and
graph wrappers live as submodules.

Canonical nano implementations live in ``soothe_nano.prompts``. Do not
duplicate or modify the re-exported symbols here; fix them in nano.
"""

from soothe_nano.prompts.context_xml import (
    build_context_sections_for_complexity,
    build_soothe_environment_section,
    build_soothe_protocols_section,
    build_soothe_thread_section,
    build_soothe_workspace_section,
)
from soothe_nano.prompts.fragments import (
    ASSISTANT_IDENTITY_FRAGMENT,
    DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT,
    SIMPLE_SYSTEM_PROMPT_FRAGMENT,
)
from soothe_nano.prompts.identity import (
    build_assistant_identity_block,
    normalize_assistant_name,
    prepend_assistant_identity,
)
from soothe_nano.prompts.project_instructions import (
    PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS,
    build_block_cached,
    load_agent_instructions,
)
from soothe_nano.prompts.system_templates import (
    EXECUTE_WORKSPACE_RULES_FRAGMENT,
    RESPONSE_LANGUAGE_HINT_FALLBACK,
    build_response_language_hint,
    build_timestamp_xml_footer,
    current_timestamp_iso,
    default_agent_system_prompt_body,
    format_complex_agent_system_prompt_core,
    uses_builtin_agent_system_prompt,
)

from .fragments import (
    APPROVED_PLAN_EXECUTE_HINT,
    ASK_MODE_ADDENDUM,
    DECOMPOSE_TASK_TOOL_DESCRIPTION,
    EVAL_DECISION_SYSTEM,
    EVAL_POLICY_SYSTEM_ADDENDUM,
    PARALLEL_NUDGE_ADDENDUM,
    PLAN_MODE_ADDENDUM,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    THREAD_USER_HINT_CHILD_FRAGMENT,
    THREAD_USER_HINT_ROOT_FRAGMENT,
    WESTWORLD_ESCALATION_ADDENDUM,
    WESTWORLD_FANOUT_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
)


def user_finish_or_split_hint_lines(*, is_dag_root: bool) -> list[str]:
    """One-line user reminder (policy lives in system + tool schemas)."""
    if is_dag_root:
        return [THREAD_USER_HINT_ROOT_FRAGMENT]
    return [THREAD_USER_HINT_CHILD_FRAGMENT]


__all__ = [
    "APPROVED_PLAN_EXECUTE_HINT",
    "ASK_MODE_ADDENDUM",
    "ASSISTANT_IDENTITY_FRAGMENT",
    "DECOMPOSE_TASK_TOOL_DESCRIPTION",
    "EVAL_DECISION_SYSTEM",
    "EVAL_POLICY_SYSTEM_ADDENDUM",
    "DEFAULT_SYSTEM_PROMPT_BODY_FRAGMENT",
    "EXECUTE_WORKSPACE_RULES_FRAGMENT",
    "PARALLEL_NUDGE_ADDENDUM",
    "PLAN_MODE_ADDENDUM",
    "PROJECT_INSTRUCTION_HEADLINE_MAX_CHARS",
    "RESPONSE_LANGUAGE_HINT_FALLBACK",
    "SIMPLE_SYSTEM_PROMPT_FRAGMENT",
    "THREAD_POLICY_SYSTEM_ADDENDUM",
    "WESTWORLD_ESCALATION_ADDENDUM",
    "WESTWORLD_FANOUT_ADDENDUM",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "build_assistant_identity_block",
    "build_block_cached",
    "build_context_sections_for_complexity",
    "build_response_language_hint",
    "build_soothe_environment_section",
    "build_soothe_protocols_section",
    "build_soothe_thread_section",
    "build_soothe_workspace_section",
    "build_timestamp_xml_footer",
    "current_timestamp_iso",
    "default_agent_system_prompt_body",
    "format_complex_agent_system_prompt_core",
    "load_agent_instructions",
    "normalize_assistant_name",
    "prepend_assistant_identity",
    "user_finish_or_split_hint_lines",
    "uses_builtin_agent_system_prompt",
]
