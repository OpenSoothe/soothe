"""System and user prompts for the veritas auto-answerer (RFC-622)."""

from __future__ import annotations

from soothe.prompts import load_agent_instructions
from soothe.sloop.clarification.protocol import ClarificationRequest

_SYSTEM_PROMPT = """You are veritas, an answerer subagent.

Your job: a planning agent has paused to ask the originating user a clarification
question. You stand in for that user. Answer as the user most likely would have,
grounded in the user's original request, the goal description, and the global
context provided.

You MUST respond in valid JSON format matching the VeritasAnswerSchema:
- `answers`: list of strings, one per question
- `confidence`: float between 0.0 and 1.0
- `defer`: boolean, true if you cannot answer confidently
- `rationale`: brief explanation of your reasoning

Hard rules:
1. NEVER ask a clarification question back. If you genuinely cannot answer,
   set `defer=true` so a human can be brought in. Do not respond with a question.
2. Answer concisely and concretely. Imperative phrasing preferred.
3. Calibrate `confidence` honestly: 0.9+ only when the answer is essentially
   stated by the user request; 0.5-0.8 when reasonable inference is required;
   below 0.4 means you are guessing and should consider defer.
4. Provide one answer per question, in the same order as `questions`.
5. Keep `rationale` to one or two sentences citing the evidence you relied on
   (user request, plan goal, recent step output, etc.).
6. When a `=== Project instructions ===` section is present, treat it as the
   authoritative rules of the repo you are working in. Do not propose answers
   that contradict those instructions (e.g. file placement, terminology,
   forbidden heuristics). If the instructions resolve the clarification, answer
   with high confidence; if they are silent or ambiguous, fall back to the
   other context."""


def build_veritas_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_veritas_user_prompt(
    request: ClarificationRequest,
    *,
    max_context_steps: int = 8,
    agent_instructions_max_chars: int = 25_000,
) -> str:
    """Render the per-request context for veritas.

    The workspace's project instructions (``AGENTS.md`` preferred, then
    ``CLAUDE.md``) are loaded via the shared loader and inlined as an
    ``=== Project instructions ===`` section so veritas's answers respect the
    target repo's guidance — the same instructions the host CoreAgent and
    synthesis prompts already receive. ``LoopStateView.workspace_summary``
    carries the thread workspace path at all three origins (execute,
    delegate, rail pause), which the loader resolves relative to.

    ``agent_instructions_max_chars`` defaults to the loader's own cap
    (25,000) so a typical ``AGENTS.md`` / ``CLAUDE.md`` inlines verbatim —
    the full project rules reach veritas, not a truncated headline. Only
    unusually large files degrade to a partial headline + ``read_file`` hint.
    """
    view = request.loop_state
    lines: list[str] = []
    lines.append("=== Original user request ===")
    lines.append(view.user_request.strip() or "(none)")
    lines.append("")
    lines.append("=== Goal description ===")
    lines.append(view.goal_description.strip() or "(none)")
    if view.intent_classification:
        lines.append("")
        lines.append(f"=== Intent classification === {view.intent_classification}")
    if view.plan_summary:
        lines.append("")
        lines.append("=== Plan summary ===")
        lines.append(view.plan_summary.strip())
    if view.workspace_summary:
        lines.append("")
        lines.append("=== Workspace summary ===")
        lines.append(view.workspace_summary.strip())

    # Project instructions (AGENTS.md / CLAUDE.md) from the workspace root.
    # workspace_summary holds the thread workspace path string (RFC-103). When
    # the path is absent or no instruction file exists, the loader returns None
    # and the section is skipped — veritas falls back to context-only answering.
    block = load_agent_instructions(
        view.workspace_summary,
        headline_max_chars=agent_instructions_max_chars,
    )
    if block:
        lines.append("")
        lines.append("=== Project instructions ===")
        lines.append(block.strip())

    if view.active_skills:
        lines.append("")
        lines.append(f"=== Active skills === {', '.join(view.active_skills)}")
    if view.active_mcp_servers:
        lines.append("")
        lines.append(f"=== Active MCP servers === {', '.join(view.active_mcp_servers)}")

    if view.recent_step_outputs:
        recent = list(view.recent_step_outputs)[-max_context_steps:]
        lines.append("")
        lines.append(f"=== Recent step outputs (last {len(recent)}) ===")
        for i, out in enumerate(recent, 1):
            lines.append(f"--- step {i} ---")
            lines.append(out.strip())

    lines.append("")
    lines.append(f"=== Iteration === {view.iteration}")
    lines.append("")
    lines.append("=== Questions to answer ===")
    for i, q in enumerate(request.questions, 1):
        lines.append(f"{i}. {q}")

    return "\n".join(lines)


__all__ = ["build_veritas_system_prompt", "build_veritas_user_prompt"]
