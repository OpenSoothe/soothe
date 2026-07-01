"""Schema-level tests for the ``kind``/``questions`` fields (IG-462)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from soothe.foundation.sloop.state.schemas import (
    PlanGenerateStep,
    StepAction,
    plan_generate_steps_to_step_actions,
    step_actions_to_plan_generate_steps,
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


class TestConverterRoundTrips:
    def test_plan_generate_to_step_action_preserves_ask_user(self) -> None:
        src = [
            PlanGenerateStep(
                id="Q-01",
                description="ask about target format",
                kind="ask_user",
                questions=["Which format?"],
            )
        ]
        converted = plan_generate_steps_to_step_actions(src)
        assert len(converted) == 1
        assert isinstance(converted[0], StepAction)
        assert converted[0].id == "Q-01"
        assert converted[0].kind == "ask_user"
        assert converted[0].questions == ["Which format?"]

    def test_step_action_to_plan_generate_preserves_ask_user(self) -> None:
        src = [
            StepAction(
                id="Q-02",
                description="ask user",
                kind="ask_user",
                questions=["A?", "B?"],
            )
        ]
        converted = step_actions_to_plan_generate_steps(src)
        assert len(converted) == 1
        assert isinstance(converted[0], PlanGenerateStep)
        assert converted[0].kind == "ask_user"
        assert converted[0].questions == ["A?", "B?"]

    def test_round_trip_action_kind_unchanged(self) -> None:
        src = [
            PlanGenerateStep(id="01", description="explore"),
            PlanGenerateStep(id="02", description="report"),
        ]
        actions = plan_generate_steps_to_step_actions(src)
        back = step_actions_to_plan_generate_steps(actions)
        assert all(s.kind == "action" for s in back)
        assert all(s.questions is None for s in back)
        assert [s.id for s in back] == ["01", "02"]

    def test_converter_copies_questions_by_value(self) -> None:
        """Mutating the converted step's questions must not bleed back to source."""
        src = [
            PlanGenerateStep(
                id="Q-03",
                description="ask",
                kind="ask_user",
                questions=["Which?"],
            )
        ]
        converted = plan_generate_steps_to_step_actions(src)
        assert converted[0].questions is not src[0].questions
        converted[0].questions.append("Extra?")
        assert src[0].questions == ["Which?"]
