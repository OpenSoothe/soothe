"""Plan-generate fragment: wire schema contract + bounded discovery guidance."""

from soothe.sloop.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_uses_wire_schema_fields() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "reasoning``, ``steps``, optional ``clarify``" in text
    assert "dependencies``: REQUIRED on every step" in text
    assert "Do not emit ``type``, ``execution_mode``, ``full_description``, or ``kind``" in text
    assert "Runtime derives ``execution_mode``" in text
    assert "plan_action" not in text
    assert "``subagent``" not in text  # wire uses ``delegate``, not step subagent field
    assert "execution_hint" not in text
    assert "evidence_refs" not in text
    assert "supportive_evidence" not in text


def test_plan_generate_execution_policy_uses_readonly_discovery_wording() -> None:
    from soothe.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Discovery" in EXECUTION_POLICIES_FRAGMENT
    assert "supportive_evidence" not in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_per_wave_hard_limit() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "Return at most 10 steps per plan wave" in text


def test_execution_policies_per_wave_cap() -> None:
    from soothe.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "At most **10 steps per plan wave**" in EXECUTION_POLICIES_FRAGMENT
    assert "runtime truncates extras" in EXECUTION_POLICIES_FRAGMENT


def test_execution_policies_subagent_delegation_guidance() -> None:
    from soothe.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Subagent delegation" in EXECUTION_POLICIES_FRAGMENT
    assert "planner" in EXECUTION_POLICIES_FRAGMENT
    assert "intake/slash routed" in EXECUTION_POLICIES_FRAGMENT
    assert "``planner`` only" not in EXECUTION_POLICIES_FRAGMENT


def test_execution_policies_forbids_sequential_mode() -> None:
    from soothe.sloop.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "never ``sequential``" in EXECUTION_POLICIES_FRAGMENT
    assert "only ``parallel`` or ``dependency``" in EXECUTION_POLICIES_FRAGMENT


def test_plan_generate_delegate_rules_default_null() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "Default: omit / null" in text
    assert "never plan-wave delegates" in text or "never plan-wave" in text
    assert "``planner`` among built-ins" not in text
    assert "Leave ``delegate`` null" in text


def test_plan_generate_preserves_contract_guards() -> None:
    """Regression: wire prompt must retain schema-critical rules."""
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "clarify.questions" in text
    assert "exclusive with non-empty ``steps``" in text
    assert "iteration 0" in text
    assert len(text) < 4500  # guard against prompt bloat (was ~5900 bytes pre-condense)
