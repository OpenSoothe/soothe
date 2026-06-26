"""Tests for RFC-214 user message envelopes (scenario-based format, IG-510)."""

from __future__ import annotations

import warnings

from soothe.foundation.loop.prompts.user_message import (
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
    assert "TIMESTAMP:" in msg


def test_execute_message_uses_goal_label() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Do the thing",
        execution_hints=None,
    )
    assert msg.startswith("GOAL:")
    assert "Do the thing" in msg
    assert "SKILL CONTEXT:" not in msg


def test_execute_message_skill_context_after_goal() -> None:
    """Skill reference appears in SKILL CONTEXT section after GOAL."""
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
    goal_idx = msg.index("GOAL:")
    skill_idx = msg.index("SKILL CONTEXT:")
    assert goal_idx < skill_idx


def test_execute_message_no_intent_section() -> None:
    """IG-510: INTENT section removed from execute-step message."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output: error list.",
    )
    assert "INTENT:" not in msg


def test_execute_message_no_task_section() -> None:
    """IG-510: TASK section removed, merged into EXECUTION HINTS."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output: error list.",
    )
    assert "TASK:" not in msg


def test_execute_message_hints_contains_task_instructions() -> None:
    """IG-510: Task instructions are merged into EXECUTION HINTS as list items."""
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Analyze logs",
        execution_hints="Expected output:\n- error list\n\nInstructions:\n- Execute the step",
    )
    assert "EXECUTION HINTS:" in msg
    assert "- Execute the step" in msg


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


def test_deprecated_envelope_wrappers_still_work() -> None:
    """Deprecated wrapper functions delegate to UserMessageBuilder."""
    from soothe.foundation.loop.prompts.user_envelope import (
        build_execute_step_envelope,
        build_plan_context_envelope,
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        exec_msg = build_execute_step_envelope("Do it")
        assert "GOAL:" in exec_msg

        plan_msg = build_plan_context_envelope(goal="Plan this")
        assert "GOAL:" in plan_msg


def test_flatten_user_message_content_extracts_goal() -> None:
    msg = "GOAL:\nSearch the repo for *.yml config\n\nEXECUTION HINTS: some hints"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo for *.yml config"


def test_flatten_user_message_content_legacy_xml() -> None:
    """Legacy XML format still extractable for backward compat."""
    msg = "<USER_QUERY>\nSearch the repo\n</USER_QUERY>"
    flat = flatten_user_message_content(msg)
    assert flat == "Search the repo"
