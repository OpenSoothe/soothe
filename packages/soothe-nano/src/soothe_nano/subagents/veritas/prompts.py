"""System and user prompts for the veritas auto-answerer (RFC-622)."""

from __future__ import annotations

from soothe_nano.clarification import ClarificationRequest

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
   (user request, plan goal, recent step output, etc.)."""


def build_veritas_system_prompt() -> str:
    return _SYSTEM_PROMPT


def build_veritas_user_prompt(
    request: ClarificationRequest,
    *,
    max_context_steps: int = 8,
) -> str:
    """Render the per-request context for veritas."""
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
