"""Plan-generate fragment: flattened decision schema + bounded discovery guidance."""

from soothe.core.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_uses_flattened_decision_fields() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "plan_action, type, steps, execution_mode" in text
    assert "plan_action" in text and "StepAction" in text
    assert "supportive_evidence" not in text


def test_plan_generate_execution_policy_uses_readonly_discovery_wording() -> None:
    from soothe.core.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Readonly discovery plans" in EXECUTION_POLICIES_FRAGMENT
    assert "supportive_evidence" not in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_first_wave_hard_limit() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "HARD LIMIT 1–2 steps" in text
    assert "execute iteration **1**" in text


def test_execution_policies_first_wave_overrides_three_step_cap() -> None:
    from soothe.core.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "execute iteration 1" in EXECUTION_POLICIES_FRAGMENT
    assert "1–2 steps only" in EXECUTION_POLICIES_FRAGMENT
    assert "never 3+" in EXECUTION_POLICIES_FRAGMENT
