"""Prompt template and formatter for RFC-226 continuation-assess LLM call.

The continuation-assess prompt is a single-turn structured-output call that
discriminates a follow-up agentic query between a one-shot bootstrap (answer
from prior context) and a full ``plan_generate`` escalation (new tools or
multi-step work). Kept in its own module to avoid bloating ``planner.py``
or the heavyweight ``PromptBuilder``; the discriminator is intentionally
lightweight and self-contained.
"""

from __future__ import annotations

from soothe.utils.text_preview import preview_first

LOOP_CONTINUATION_ASSESS_PROMPT = """\
You are deciding how to handle a follow-up query in an in-progress conversation loop.

CURRENT REQUEST:
{current_goal}

PRIOR GOALS IN THIS LOOP:
{prior_goals_block}

AVAILABLE CAPABILITIES:
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
"""


def format_loop_continuation_assess_prompt(
    *,
    current_goal: str,
    prior_goals: list[dict],
    capabilities: list[str],
) -> str:
    """Render LOOP_CONTINUATION_ASSESS_PROMPT with the per-call context.

    Args:
        current_goal: The new user query (``LoopState.goal``).
        prior_goals: Output of ``_prior_goal_summaries(checkpoint)``; each dict has
            ``goal_id``, ``goal_text``, ``completion``, ``step_count``,
            ``current_plan_action``.
        capabilities: Available tool + subagent names (top 30 used).

    Returns:
        Formatted prompt string suitable for a single ``HumanMessage``.
    """
    if prior_goals:
        rows = []
        for g in prior_goals:
            rows.append(
                f"  - {g['goal_id']} | text={g['goal_text'][:60]!r} | "
                f"completion={preview_first(g.get('completion', ''), 800)!r} | "
                f"steps={g.get('step_count', 0)} | "
                f"last={g.get('current_plan_action', '')[:60]!r}"
            )
        prior_block = "\n".join(rows)
    else:
        prior_block = "  (none)"

    if capabilities:
        caps_block = ", ".join(capabilities[:30])
    else:
        caps_block = "(none)"

    return LOOP_CONTINUATION_ASSESS_PROMPT.format(
        current_goal=current_goal,
        prior_goals_block=prior_block,
        capabilities_block=caps_block,
    )
