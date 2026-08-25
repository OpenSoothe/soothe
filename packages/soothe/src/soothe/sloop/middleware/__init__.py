"""Unified middleware package for host agent behavior overrides.

Single import surface for all StrangeLoop host middlewares:

- ``AskUserPromptMiddleware`` — inject ``ask_user`` gate directive into the system prompt.
- ``GoalStepGuardMiddleware`` — read-only policy during goal-completion synthesis.
- ``IntakeOnlyTaskGuardMiddleware`` — block ``task`` calls to intake-only specialists.
- ``GeneralPurposeVariantGuardMiddleware`` — redirect ``task``→GP to the readonly variant on plan/ask steps (requires ``general_purpose_subagent="per_step"``).
- ``DecomposeTaskMiddleware`` — inject ``decompose_task`` + THREAD policy on step threads.
- ``EvalStepMiddleware`` — coverage-audit policy (full tool surface) for Eval steps.
- ``WestWorldMiddleware`` — fixed directive phrase → fixed agent behavior.

Domain packages (``sloop.decompose``, ``sloop.eval``) remain the canonical
homes of their middleware *implementations* (they co-locate with their
runtime / tool / prompt fragments). This package re-exports them so callers
have one stable import path and the two host guards live here physically.
"""

from soothe.sloop.decompose.middleware import DecomposeTaskMiddleware
from soothe.sloop.eval.middleware import EvalStepMiddleware
from soothe.sloop.middleware.ask_user_prompt import AskUserPromptMiddleware
from soothe.sloop.middleware.goal_step_guard import GoalStepGuardMiddleware
from soothe.sloop.middleware.gp_variant_guard import (
    GeneralPurposeVariantGuardMiddleware,
)
from soothe.sloop.middleware.intake_task_guard import IntakeOnlyTaskGuardMiddleware
from soothe.sloop.middleware.westworld import WestWorldMiddleware

__all__ = [
    "AskUserPromptMiddleware",
    "DecomposeTaskMiddleware",
    "EvalStepMiddleware",
    "GeneralPurposeVariantGuardMiddleware",
    "GoalStepGuardMiddleware",
    "IntakeOnlyTaskGuardMiddleware",
    "WestWorldMiddleware",
]
