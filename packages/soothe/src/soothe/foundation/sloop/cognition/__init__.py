"""StrangeLoop plan cognition — LLM assess/generate, parsing, bypasses (IG-537).

Step plan *state* lives in ``soothe.foundation.context.planning``.
This package owns plan-phase *reasoning* only.
"""

from soothe.foundation.sloop.cognition.continuation_prompts import (
    LOOP_CONTINUATION_ASSESS_PROMPT,
    format_loop_continuation_assess_prompt,
)
from soothe.foundation.sloop.cognition.ledger_compaction import (
    compact_execute_human_content,
    compact_plan_assess_ai_dump,
    compact_planning_human_content,
)
from soothe.foundation.sloop.cognition.parser import parse_plan_from_text
from soothe.foundation.sloop.cognition.phase import PlanPhase
from soothe.foundation.sloop.cognition.planner import LLMPlanner
from soothe.foundation.sloop.cognition.structured_plan_parser import parse_plan_with_config
from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan

__all__ = [
    "LLMPlanner",
    "LOOP_CONTINUATION_ASSESS_PROMPT",
    "PlanPhase",
    "build_trivial_plan",
    "compact_execute_human_content",
    "compact_plan_assess_ai_dump",
    "compact_planning_human_content",
    "format_loop_continuation_assess_prompt",
    "parse_plan_from_text",
    "parse_plan_with_config",
]
