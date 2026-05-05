"""Plan-generate fragment: flattened decision schema + bounded discovery guidance."""

from soothe.core.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_uses_flattened_decision_fields() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "plan_action, type, steps, execution_mode" in text
    assert "decision fields" in text
    assert "supportive_evidence" not in text


def test_plan_generate_execution_policy_uses_readonly_discovery_wording() -> None:
    from soothe.core.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Readonly discovery plans" in EXECUTION_POLICIES_FRAGMENT
    assert "supportive_evidence" not in EXECUTION_POLICIES_FRAGMENT
