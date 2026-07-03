"""Legacy RFC-226 continuation-assess prompt helpers.

Superseded by unified planner assembly (``LLMPlanner.assess_continuation`` via
``PromptBuilder.build_plan_messages``). Prior goal completion is projected from
``goal_completion`` ledger pairs — not pasted inline.
"""

from __future__ import annotations

from soothe.foundation.sloop.engine.continuation_context import ledger_goal_completion_text

LOOP_CONTINUATION_ASSESS_PROMPT = """\
You are deciding how to handle a follow-up query in an in-progress conversation loop.

CURRENT REQUEST:
{current_goal}

{prior_goal_completion_section}AVAILABLE CAPABILITIES:
{capabilities_block}

DECISION CRITERIA:
- Choose "bootstrap" when the current request can be answered using prior conversation
  context alone (e.g., "translate that", "summarize the result", "explain it in chinese")
  with no new tools or cross-domain work.
- Choose "plan_generate" when the current request needs multiple steps, new tool calls,
  addresses a topic not covered by prior goals, OR when the user says continue/resume/proceed
  and the prior goal completion report contains recommended next actions to implement.
- For continue/resume/proceed: prefer "plan_generate" when prior completion lists
  recommendations, high-priority items, or follow-up implementation work.

Return a ContinuationAssessment JSON object with fields: action, reasoning, goal_progress.
- reasoning: one first-person sentence (≤240 chars), e.g. "I'll …" or "I need … because …"
"""


def format_loop_continuation_assess_prompt(
    *,
    current_goal: str,
    loop_messages: list | None = None,
    capabilities: list[str],
) -> str:
    """Render legacy continuation-assess prompt (prefer unified planner assembly).

    Args:
        current_goal: The new user query (``LoopState.goal``).
        loop_messages: Orchestration ledger for ``goal_completion`` lookup.
        capabilities: Available tool + subagent names (top 30 used).

    Returns:
        Formatted prompt string suitable for a single ``HumanMessage``.
    """
    body = ledger_goal_completion_text(loop_messages or [])
    prior_section = ""
    if body:
        prior_section = f"PRIOR GOAL COMPLETION:\n{body}\n\n"

    if capabilities:
        caps_block = ", ".join(capabilities[:30])
    else:
        caps_block = "(none)"

    return LOOP_CONTINUATION_ASSESS_PROMPT.format(
        current_goal=current_goal,
        prior_goal_completion_section=prior_section,
        capabilities_block=caps_block,
    )
