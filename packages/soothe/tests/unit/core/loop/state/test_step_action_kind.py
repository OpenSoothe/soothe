"""Schema-level tests for the ``kind``/``questions`` fields."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe.sloop.state.schemas import (
    PlanGenerateStep,
    StepAction,
)


class TestStepActionKindDefaults:
    def test_step_action_defaults_to_action_kind(self) -> None:
        step = StepAction(description="do a thing")
        assert step.kind == "action"
        assert step.questions is None

    def test_plan_generate_step_defaults_to_action_kind(self) -> None:
        step = PlanGenerateStep(description="do a thing")
        assert step.kind == "action"
        assert step.questions is None


class TestAskUserValidation:
    def test_ask_user_requires_questions(self) -> None:
        with pytest.raises(ValidationError, match="ask_user step requires non-empty questions"):
            StepAction(description="ask the user", kind="ask_user")

    def test_ask_user_with_empty_list_rejected(self) -> None:
        with pytest.raises(ValidationError, match="ask_user step requires non-empty questions"):
            StepAction(description="ask the user", kind="ask_user", questions=[])

    def test_ask_user_with_questions_accepted(self) -> None:
        step = StepAction(
            description="ask the user",
            kind="ask_user",
            questions=["Which format do you want?"],
        )
        assert step.kind == "ask_user"
        assert step.questions == ["Which format do you want?"]

    def test_plan_generate_step_ask_user_requires_questions(self) -> None:
        with pytest.raises(ValidationError, match="ask_user step requires non-empty questions"):
            PlanGenerateStep(description="ask the user", kind="ask_user")

    def test_action_kind_with_questions_is_permitted_but_not_meaningful(self) -> None:
        # questions on a non-ask_user step are ignored at the relay layer; the
        # validator only enforces the inverse (ask_user MUST have questions).
        step = StepAction(description="run a tool", kind="action", questions=["?"])
        assert step.kind == "action"
