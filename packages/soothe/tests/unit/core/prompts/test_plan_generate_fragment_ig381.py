"""Plan-generate fragment: flattened decision schema + bounded discovery guidance."""

from soothe.foundation.sloop.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_uses_flattened_decision_fields() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "type, steps, execution_mode" in text
    assert "plan_action" not in text
    assert "subagent" not in text
    assert "evidence_refs" not in text
    assert "supportive_evidence" not in text
    assert "Never output ``sequential``" in text
    assert "only ``parallel`` or ``dependency``" in text


def test_plan_generate_execution_policy_uses_readonly_discovery_wording() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Discovery" in EXECUTION_POLICIES_FRAGMENT
    assert "supportive_evidence" not in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_per_wave_hard_limit() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "Return at most 10 steps per plan wave" in text


def test_execution_policies_per_wave_cap() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "At most **10 steps per plan wave**" in EXECUTION_POLICIES_FRAGMENT
    assert "runtime truncates extras" in EXECUTION_POLICIES_FRAGMENT


def test_execution_policies_forbids_sequential_mode() -> None:
    from soothe.foundation.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "never ``sequential``" in EXECUTION_POLICIES_FRAGMENT
    assert "only ``parallel`` or ``dependency``" in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_preserves_contract_guards() -> None:
    """Regression: condensed prompt must retain schema-critical rules."""
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "full_description" in text
    assert "kind=ask_user" in text or 'kind="ask_user"' in text
    assert "Language lock" in text
    assert "same natural language as the current goal statement" in text
    assert "NEVER at iteration 0" in text
    assert len(text) < 3500  # guard against prompt bloat (was ~5900 bytes pre-condense)
