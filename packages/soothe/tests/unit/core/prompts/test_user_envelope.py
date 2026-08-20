"""Tests for RFC-214 user message envelopes (scenario-based format)."""

from __future__ import annotations

from soothe.prompts.user_message import (
    UserMessageBuilder,
    flatten_user_message_content,
)


def test_execute_message_omits_response_language_hint() -> None:
    """Language hint lives in the system prompt now, not the per-turn message."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Read README",
    )
    assert "response_language_hint" not in msg.lower()
    assert "RESPONSE_LANGUAGE_HINT" not in msg
    assert "TIMESTAMP:" not in msg


def test_execute_message_uses_execution_task_label() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Do the thing",
    )
    assert msg.startswith("EXECUTION TASK:")
    assert "Do the thing" in msg
    assert "GOAL:" not in msg
    assert "SKILL CONTEXT:" not in msg


def test_execute_message_vision_context_is_subordinate() -> None:
    """vision facts as VISION CONTEXT; never peer GOAL; scope instructions."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Extract labels from the screenshot",
        instructions="- Complete only this step's deliverable; do not execute work assigned to other plan steps",
        vision_context="Login form with email field and Submit button.",
    )
    assert msg.startswith("EXECUTION TASK:")
    assert "VISION CONTEXT:" in msg
    assert "Login form with email field" in msg
    assert "GOAL:" not in msg
    assert "EXECUTION TASK is authoritative scope" in msg
    assert "Do not expand work to cover the entire original user request" in msg
    task_idx = msg.index("EXECUTION TASK:")
    vision_idx = msg.index("VISION CONTEXT:")
    instr_idx = msg.index("INSTRUCTIONS:")
    assert task_idx < vision_idx < instr_idx


def test_execute_message_omits_vision_context_when_absent() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message("Solo step")
    assert "VISION CONTEXT:" not in msg
    assert "EXECUTION TASK is authoritative scope" not in msg


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
    """INTENT section removed from execute-step message."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        expected_output="- error list",
    )
    assert "INTENT:" not in msg


def test_execute_message_no_task_section() -> None:
    """TASK section removed; instructions live in INSTRUCTIONS."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        expected_output="- error list",
    )
    assert not msg.startswith("TASK:")
    assert "\n\nTASK:" not in msg


def test_execute_message_instructions_section() -> None:
    """Execute-step instructions use a dedicated INSTRUCTIONS section."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        expected_output="- error list",
        instructions="- Execute the step",
    )
    assert "EXECUTION HINTS:" not in msg
    assert "INSTRUCTIONS:" in msg
    assert "- Execute the step" in msg
    assert "Expected output:" not in msg


def test_execute_message_execution_metadata() -> None:
    """Step id and TUI card title appear in EXECUTION METADATA after INSTRUCTIONS."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Full brief for the step",
        step_id="WAA-01",
        short_description="Scan repo",
        instructions="- Run the scan",
    )
    assert "EXECUTION METADATA:" in msg
    assert "step_id: WAA-01" in msg
    assert "short_description: Scan repo" in msg
    instructions_idx = msg.index("INSTRUCTIONS:")
    metadata_idx = msg.index("EXECUTION METADATA:")
    assert instructions_idx < metadata_idx


def test_execute_message_prior_steps_section() -> None:
    """Dependent steps include PRIOR STEPS between EXECUTION TASK and INSTRUCTIONS."""
    from soothe.prompts.user_message import render_prior_steps_tree
    from soothe.sloop.engine.execute.step_predecessor_context import PriorStepSummary

    builder = UserMessageBuilder()
    prior_steps = render_prior_steps_tree(
        [
            PriorStepSummary(
                step_id="01",
                description="Run verification script",
                status="completed",
            )
        ],
        evidence_in_ledger=True,
    )
    msg = builder.build_execute_step_message(
        "Fix identified failures",
        instructions="- Apply fixes from prior outcomes",
        prior_steps=prior_steps,
    )
    assert "PRIOR STEPS:" in msg
    assert "Run verification script" in msg
    assert "(completed)" in msg
    assert "see prior assistant message" in msg
    task_idx = msg.index("EXECUTION TASK:")
    prior_idx = msg.index("PRIOR STEPS:")
    instructions_idx = msg.index("INSTRUCTIONS:")
    assert task_idx < prior_idx < instructions_idx


def test_execute_message_no_prior_step_evidence_section() -> None:
    """Predecessor context is projected from the ledger, not inlined in the envelope."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Fix identified failures",
        instructions="- Apply fixes from prior ledger evidence",
    )
    assert "PRIOR STEP EVIDENCE:" not in msg
    assert "Fix identified failures" in msg


def test_flatten_user_message_content_extracts_execution_task() -> None:
    msg = "EXECUTION TASK:\nSearch the repo for *.yml config\n\nINSTRUCTIONS:\n- some hints"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo for *.yml config"


def test_flatten_user_message_content_extracts_plan_goal() -> None:
    msg = "GOAL:\nAssess completion for the parent objective\n\nTASK: assess"
    flat = flatten_user_message_content(msg)
    assert flat == "Assess completion for the parent objective"


def test_flatten_user_message_content_extracts_legacy_execute_goal() -> None:
    msg = "GOAL:\nSearch the repo for *.yml config\n\nINSTRUCTIONS:\n- some hints"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo for *.yml config"
