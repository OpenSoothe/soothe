"""Tests for RFC-214 user message envelopes (scenario-based format, IG-508)."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.user_message import (
    UserMessageBuilder,
    flatten_user_message_content,
)


def test_execute_message_omits_response_language_hint() -> None:
    """Language hint lives in the system prompt now, not the per-turn message."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Read README",
        execution_hints=None,
    )
    assert "response_language_hint" not in msg.lower()
    assert "RESPONSE_LANGUAGE_HINT" not in msg
    assert "TIMESTAMP:" not in msg


def test_execute_message_uses_execution_task_label() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Do the thing",
        execution_hints=None,
    )
    assert msg.startswith("EXECUTION TASK:")
    assert "Do the thing" in msg
    assert "GOAL:" not in msg
    assert "SKILL CONTEXT:" not in msg


def test_execute_message_skill_context_after_execution_task() -> None:
    """Skill reference appears in SKILL CONTEXT section after EXECUTION TASK."""
    skill_ref = (
        "Skill: demo\n\n"
        "Skill folder: /skills/demo\n"
        "(Additional files may live under this directory — use filesystem tools to "
        "read them when SKILL.md is not sufficient.)\n\n" + ("body line\n" * 5)
    )
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Run the planned step",
        skill_context=skill_ref,
    )
    assert "SKILL CONTEXT:" in msg
    assert "Skill: demo" in msg
    assert "Skill folder: /skills/demo" in msg
    assert "User instruction" not in msg
    task_idx = msg.index("EXECUTION TASK:")
    skill_idx = msg.index("SKILL CONTEXT:")
    assert task_idx < skill_idx


def test_execute_message_no_intent_section() -> None:
    """IG-508: INTENT section removed from execute-step message."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output: error list.",
    )
    assert "INTENT:" not in msg


def test_execute_message_no_task_section() -> None:
    """IG-508: TASK section removed, merged into EXECUTION HINTS."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output: error list.",
    )
    assert not msg.startswith("TASK:")
    assert "\n\nTASK:" not in msg


def test_execute_message_hints_contains_task_instructions() -> None:
    """IG-508: Task instructions are merged into EXECUTION HINTS as list items."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output:\n- error list\n\nInstructions:\n- Execute the step",
    )
    assert "EXECUTION HINTS:" in msg
    assert "- Execute the step" in msg


def test_execute_message_prior_step_evidence_section() -> None:
    """Dependent steps include PRIOR STEP EVIDENCE between EXECUTION TASK and EXECUTION HINTS."""
    builder = UserMessageBuilder()
    evidence = "Step 01 — verify (completed)\n---\n✗ F821 undefined name `Any`"
    msg = builder.build_execute_step_message(
        "Fix identified failures",
        execution_hints="Instructions:\n- Apply fixes from evidence",
        predecessor_evidence=evidence,
    )
    assert "PRIOR STEP EVIDENCE:" in msg
    assert "F821 undefined name `Any`" in msg
    task_idx = msg.index("EXECUTION TASK:")
    evidence_idx = msg.index("PRIOR STEP EVIDENCE:")
    hints_idx = msg.index("EXECUTION HINTS:")
    assert task_idx < evidence_idx < hints_idx


def test_execute_message_omits_prior_step_evidence_when_absent() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message("Solo step")
    assert "PRIOR STEP EVIDENCE:" not in msg


def test_plan_assess_message_omits_intent_section() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(goal="analyze architecture")
    assert "GOAL:" in msg
    assert "INTENT:" not in msg


def test_plan_generate_message_omits_intent_section() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(goal="analyze architecture")
    assert "GOAL:" in msg
    assert "INTENT:" not in msg


def test_plan_assess_message_omits_goal_progress_even_with_bundle() -> None:
    from soothe.foundation.context.projection import ContextBundle

    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(
        goal="analyze architecture",
        context_bundle=ContextBundle(goal_progress="Steps: 2/5 completed"),
    )
    assert "GOAL PROGRESS:" not in msg
    assert "2/5 completed" not in msg


def test_plan_generate_message_omits_goal_progress_even_with_bundle() -> None:
    from soothe.foundation.context.projection import ContextBundle

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="analyze architecture",
        context_bundle=ContextBundle(goal_progress="Steps: 2/5 completed"),
    )
    assert "GOAL PROGRESS:" not in msg
    assert "2/5 completed" not in msg


def test_plan_assess_message_uses_goal_label() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(
        goal="write a image understanding pipeline",
    )
    assert "GOAL:" in msg
    assert "write a image understanding pipeline" in msg
    assert "GOAL PROGRESS:" not in msg
    assert "Execute iteration" not in msg


def test_plan_assess_message_omits_response_language_hint() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(
        goal="Résumé demandé",
    )
    assert "response_language_hint" not in msg.lower()
    assert "RESPONSE_LANGUAGE_HINT" not in msg


def test_plan_assess_message_skill_reference_when_provided() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(
        goal="shanghai tomorrow",
        skill_context="Skill: weather\nSkill folder: /skills/weather\n\nWeather skill body here",
    )
    assert "SKILL REFERENCE:" in msg
    assert "Weather skill body here" in msg
    goal_idx = msg.index("GOAL:")
    skill_idx = msg.index("SKILL REFERENCE:")
    assert goal_idx < skill_idx


def test_plan_assess_message_no_skill_reference_when_absent() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_assess_message(goal="plain goal")
    assert "SKILL REFERENCE:" not in msg
    msg_empty = builder.build_plan_assess_message(goal="plain goal", skill_context="  ")
    assert "SKILL REFERENCE:" not in msg_empty


def test_plan_generate_message_includes_step_id_hint() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="do stuff",
        step_id_hint="Next step IDs start at 03",
    )
    assert "STEP ID HINT:" in msg
    assert "03" in msg


def test_plan_generate_message_includes_step_anchor_registry() -> None:
    builder = UserMessageBuilder()
    registry = (
        "Completed (valid cross-wave dependency targets — use EXACT ids):\n"
        "- KFA-01 [completed] Run verify"
    )
    msg = builder.build_plan_generate_message(
        goal="fix lint",
        step_anchor_registry=registry,
    )
    assert "STEP ANCHOR REGISTRY:" in msg
    assert "KFA-01 [completed]" in msg


def test_envelope_builder_direct_usage() -> None:
    """Use UserMessageBuilder directly (deprecated wrappers removed)."""
    builder = UserMessageBuilder()
    exec_msg = builder.build_execute_step_message("Do it")
    assert "EXECUTION TASK:" in exec_msg
    assert "GOAL:" not in exec_msg

    plan_msg = builder.build_plan_assess_message(goal="Plan this")
    assert "GOAL:" in plan_msg


def test_flatten_user_message_content_extracts_execution_task() -> None:
    msg = "EXECUTION TASK:\nSearch the repo for *.yml config\n\nEXECUTION HINTS: some hints"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo for *.yml config"


def test_flatten_user_message_content_extracts_plan_goal() -> None:
    msg = "GOAL:\nAssess completion for the parent objective\n\nTASK: assess"
    flat = flatten_user_message_content(msg)
    assert flat == "Assess completion for the parent objective"


def test_flatten_user_message_content_extracts_legacy_execute_goal() -> None:
    msg = "GOAL:\nSearch the repo for *.yml config\n\nEXECUTION HINTS: some hints"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo for *.yml config"


def test_flatten_user_message_content_legacy_xml() -> None:
    """Legacy XML format still extractable for backward compat."""
    msg = "<USER_QUERY>\nSearch the repo\n</USER_QUERY>"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo"


def test_plan_generate_omits_redundant_goal_lineage() -> None:
    from soothe.foundation.context.projection import ContextBundle

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="count folders",
        context_bundle=ContextBundle(goal_lineage="count folders"),
    )
    assert "GOAL LINEAGE:" not in msg


def test_plan_generate_keeps_hierarchical_goal_lineage() -> None:
    from soothe.foundation.context.projection import ContextBundle

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="Child task",
        context_bundle=ContextBundle(goal_lineage="Root mission → Child task"),
    )
    assert "GOAL LINEAGE:" in msg
    assert "Root mission → Child task" in msg


def test_plan_generate_skips_goal_lineage_when_prior_goal_completion_present() -> None:
    from soothe.foundation.context.projection import ContextBundle

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="continue",
        prior_goal_completion="Prior synthesis with recommended next actions.",
        context_bundle=ContextBundle(goal_lineage="Root → continue"),
    )
    assert "PRIOR GOAL COMPLETION:" in msg
    assert "GOAL LINEAGE:" not in msg


def test_plan_generate_includes_prior_goals_from_bundle() -> None:
    from soothe.foundation.context.projection import ContextBundle, PriorGoalSummary

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="continue",
        context_bundle=ContextBundle(
            prior_goals=[
                PriorGoalSummary(
                    goal_id="g0",
                    description="count folders in root",
                    status="completed",
                    step_summary="  - 01: List directories",
                )
            ]
        ),
    )
    assert "PRIOR GOALS:" in msg
    assert "count folders in root" in msg
    assert "List directories" in msg
    prior_goals_idx = msg.index("PRIOR GOALS:")
    goal_idx = msg.index("GOAL:")
    assert goal_idx < prior_goals_idx


def test_plan_generate_context_section_order() -> None:
    from soothe.foundation.context.projection import ContextBundle, PriorGoalSummary
    from soothe.foundation.sloop.state.schemas import PriorProgressDigest, ToolCallHead

    builder = UserMessageBuilder()
    msg = builder.build_plan_generate_message(
        goal="Child task",
        prior_goal_completion="Full prior report.",
        step_id_hint="Use step ids 03, 04.",
        prior_progress=PriorProgressDigest(
            iteration=0,
            wave_index=0,
            steps_completed=1,
            derived_progress_hint="medium",
            tool_calls=[ToolCallHead(name="read_file", head="readme")],
        ),
        context_bundle=ContextBundle(
            goal_lineage="Root mission → Child task",
            step_lineage="Pending step reasoning",
            prior_goals=[
                PriorGoalSummary(
                    goal_id="g0",
                    description="prior work",
                    status="completed",
                    step_summary="",
                )
            ],
        ),
        skill_context="Skill body",
    )
    labels = [
        "GOAL:",
        "PRIOR GOAL COMPLETION:",
        "PRIOR GOALS:",
        "PRIOR PROGRESS:",
        "STEP LINEAGE:",
        "SKILL REFERENCE:",
        "STEP ID HINT:",
        "TASK:",
    ]
    indices = [msg.index(label) for label in labels]
    assert indices == sorted(indices)
    assert "GOAL LINEAGE:" not in msg
