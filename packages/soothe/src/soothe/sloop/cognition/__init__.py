"""StrangeLoop plan cognition — LLM assess/generate, parsing, bypasses (IG-537).

Step plan *state* lives in ``soothe.context``.
This package owns plan-phase *reasoning* only.
"""

from soothe.sloop.cognition.ledger_compaction import (
    compact_execute_human_content,
    compact_planning_human_content,
)
from soothe.sloop.cognition.parser import parse_plan_from_text
from soothe.sloop.cognition.phase import PlanPhase
from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.cognition.structured_plan_parser import parse_plan_with_config
from soothe.sloop.cognition.trivial_plan import build_trivial_plan

__all__ = [
    "LLMPlanner",
    "PlanPhase",
    "build_trivial_plan",
    "compact_execute_human_content",
    "compact_planning_human_content",
    "parse_plan_from_text",
    "parse_plan_with_config",
]
