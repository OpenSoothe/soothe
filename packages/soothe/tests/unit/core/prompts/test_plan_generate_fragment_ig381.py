"""Plan-generate fragment: flattened decision schema + bounded discovery guidance."""

from soothe.foundation.sloop.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_uses_flattened_decision_fields() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "plan_action, type, steps, execution_mode" in text
    assert "plan_action" in text
    assert "subagent" not in text
    assert "evidence_refs" not in text
    assert "supportive_evidence" not in text
    assert "Never output ``sequential``" in text
    assert "only ``parallel`` or ``dependency``" in text


def test_plan_generate_execution_policy_uses_readonly_discovery_wording() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Discovery" in EXECUTION_POLICIES_FRAGMENT
    assert "supportive_evidence" not in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_first_wave_hard_limit() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "first wave: 1–2 only" in text


def test_execution_policies_first_wave_overrides_three_step_cap() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "First wave (iteration 1" in EXECUTION_POLICIES_FRAGMENT
    assert "1–2 steps" in EXECUTION_POLICIES_FRAGMENT
    assert "never 3+" in EXECUTION_POLICIES_FRAGMENT


def test_execution_policies_forbids_sequential_mode() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "never ``sequential``" in EXECUTION_POLICIES_FRAGMENT
    assert "only ``parallel`` or ``dependency``" in EXECUTION_POLICIES_FRAGMENT
