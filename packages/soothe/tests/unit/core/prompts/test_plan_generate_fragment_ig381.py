"""Plan-generate fragment: progressive planning + supportive_evidence + explore bundle (IG-381)."""

from soothe.core.prompts.fragments import PLAN_GENERATE_INSTRUCTIONS_FRAGMENT


def test_plan_generate_includes_progressive_and_supportive_evidence_ig381() -> None:
    text = PLAN_GENERATE_INSTRUCTIONS_FRAGMENT
    assert "Progressive planning" in text
    assert "supportive_evidence" in text
    assert "No prior tool/subagent results" in text


def test_plan_generate_includes_explore_read_heavy_policy_reference_ig381() -> None:
    from soothe.core.prompts.fragments import EXECUTION_POLICIES_FRAGMENT

    assert "Explore / read-heavy plans" in EXECUTION_POLICIES_FRAGMENT
    assert "subagent: explore" in EXECUTION_POLICIES_FRAGMENT
