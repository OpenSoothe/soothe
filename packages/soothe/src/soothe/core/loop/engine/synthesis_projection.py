"""Project AgentLoop state into user-safe synthesis context (RFC-603, RFC-214).

Synthesis must not receive raw ``loop_messages`` (plan envelopes, ledger stubs, or
orchestration metadata). This module builds a bounded evidence payload and pairs it
with a system prompt that uses only end-user vocabulary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from soothe.core.loop.engine.scenario_classifier import ScenarioClassification
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.core.loop.utils.stream_normalize import extract_text_from_message_content
from soothe.core.prompts.user_envelope import (
    _EMPTY_SKILL_USER_TEXT_PLACEHOLDER,
    _goal_text_for_execute_step_envelope,
)

if TYPE_CHECKING:
    from soothe.core.loop.state.schemas import LoopState

# Phases excluded by ledger ``phase`` metadata (includes goal-completion ledger stubs).
_EXCLUDED_LEDGER_PHASES = frozenset(
    {
        "plan_assess",
        "plan_generate",
        "goal_completion",
        "execute_wave",
        "quiz",
    }
)


@dataclass(frozen=True)
class SynthesisUserContext:
    """User-safe inputs for final report generation."""

    user_query: str
    evidence_body: str


def normalize_user_query(goal: str | None) -> str:
    """Normalize stored goal text for the user-facing synthesis request."""
    text = _goal_text_for_execute_step_envelope(goal)
    if text == "No goal specified":
        return "No request specified"
    return text


def _extract_xml_block(text: str, tag: str) -> str | None:
    pattern = re.compile(rf"<{tag}>\s*(.*?)\s*</{tag}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1).strip()


def flatten_execute_human_content(content: str) -> str:
    """Extract task-focused text from an execute-step human envelope.

    When the message uses the RFC-214 envelope, returns ``<USER_QUERY>`` or
    ``<USER_PRIMARY_QUERY>`` body only. Otherwise returns the raw content unchanged.
    """
    text = (content or "").strip()
    if not text:
        return ""

    user_query = _extract_xml_block(text, "USER_QUERY")
    if user_query:
        return user_query

    primary = _extract_xml_block(text, "USER_PRIMARY_QUERY")
    if primary and primary != _EMPTY_SKILL_USER_TEXT_PLACEHOLDER:
        return primary

    return text


def _step_evidence_lines(state: LoopState) -> list[str]:
    lines: list[str] = []
    for result in state.step_results:
        if result.success:
            body = result.to_evidence_string(truncate=False)
        else:
            body = f"Failed: {result.error or 'unknown error'}"
        lines.append(f'<step id="{result.step_id}">{_xml_escape(body)}</step>')
    return lines


def _execute_transcript_lines(state: LoopState) -> list[str]:
    lines: list[str] = []
    if not state.loop_messages:
        return lines

    for msg in state.loop_messages:
        phase = getattr(msg, "phase", None)
        if phase in _EXCLUDED_LEDGER_PHASES:
            continue
        if phase not in (None, "execute_step"):
            continue

        if isinstance(msg, LoopHumanMessage):
            text = flatten_execute_human_content(extract_text_from_message_content(msg.content))
            if text:
                lines.append(f"<assistant_task>{_xml_escape(text)}</assistant_task>")
        elif isinstance(msg, LoopAIMessage):
            text = extract_text_from_message_content(msg.content).strip()
            if text:
                lines.append(f"<finding>{_xml_escape(text)}</finding>")

    return lines


def _xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def project_synthesis_user_context(
    state: LoopState,
    *,
    user_query: str | None = None,
) -> SynthesisUserContext:
    """Build user-safe query + evidence XML from loop state."""
    query = normalize_user_query(user_query if user_query is not None else state.goal)

    parts: list[str] = []
    step_lines = _step_evidence_lines(state)
    if step_lines:
        parts.append("<step_summaries>")
        parts.extend(f"  {line}" for line in step_lines)
        parts.append("</step_summaries>")

    transcript = _execute_transcript_lines(state)
    if transcript:
        parts.append("<work_transcript>")
        parts.extend(f"  {line}" for line in transcript)
        parts.append("</work_transcript>")

    if not parts:
        parts.append(
            "<work_transcript>\n  <finding>No detailed execution record available.</finding>\n</work_transcript>"
        )

    evidence_body = "\n".join(parts)
    return SynthesisUserContext(
        user_query=query,
        evidence_body=evidence_body,
    )


def _trim_evidence_body(body: str, max_chars: int) -> str:
    if max_chars <= 0 or len(body) <= max_chars:
        return body
    marker = "\n…[evidence truncated]\n"
    return body[: max(0, max_chars - len(marker))] + marker


def build_synthesis_human_payload(context: SynthesisUserContext) -> str:
    """Return the single human message body for synthesis (XML, user vocabulary only)."""
    return (
        f"<user_request>\n{context.user_query}\n</user_request>\n\n"
        f"<execution_evidence>\n{context.evidence_body}\n</execution_evidence>"
    )


def render_synthesis_system_prompt(classification: ScenarioClassification) -> str:
    """Render system instructions from the synthesis template (no orchestration terms)."""
    from soothe.core.prompts.loader import load_prompt_fragment

    template = load_prompt_fragment("instructions/synthesis_report_system.xml")
    focus_items = "\n".join(f"- {item}" for item in classification.contextual_focus)
    return template.render(
        scenario=classification.scenario,
        sections=classification.sections,
        contextual_focus=focus_items,
        evidence_emphasis=classification.evidence_emphasis,
    )


def build_synthesis_messages(
    state: LoopState,
    classification: ScenarioClassification,
    *,
    user_query: str | None = None,
    max_chars: int,
) -> list[BaseMessage]:
    """Assemble system + human messages for goal-completion synthesis."""
    context = project_synthesis_user_context(state, user_query=user_query)
    context = SynthesisUserContext(
        user_query=context.user_query,
        evidence_body=_trim_evidence_body(
            context.evidence_body,
            max(0, max_chars - 4096),
        ),
    )
    system_text = render_synthesis_system_prompt(classification)
    human_text = build_synthesis_human_payload(context)

    while max_chars > 0:
        total = len(system_text) + len(human_text)
        if total <= max_chars:
            break
        over = total - max_chars
        context = SynthesisUserContext(
            user_query=context.user_query,
            evidence_body=_trim_evidence_body(
                context.evidence_body, len(context.evidence_body) - over
            ),
        )
        human_text = build_synthesis_human_payload(context)
        if len(context.evidence_body) < 200:
            break

    return [
        SystemMessage(content=system_text),
        HumanMessage(content=human_text),
    ]


__all__ = [
    "SynthesisUserContext",
    "build_synthesis_human_payload",
    "build_synthesis_messages",
    "flatten_execute_human_content",
    "normalize_user_query",
    "project_synthesis_user_context",
    "render_synthesis_system_prompt",
]
