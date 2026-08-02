"""Tests for daemon vision-preflight extraction (IG-674)."""

from __future__ import annotations

from soothe.sloop.vision_context import (
    VISION_SUMMARY_HEADER,
    extract_vision_summary,
    format_image_facts_for_brief,
    merge_vision_instructions,
)


def _enriched(user: str, summary: str) -> str:
    return f"{user}\n\n{VISION_SUMMARY_HEADER}\n{summary}\n---\n"


def test_extract_vision_summary_present() -> None:
    text = _enriched("Describe this UI", "A login form with email and password fields.")
    assert extract_vision_summary(text) == "A login form with email and password fields."


def test_extract_vision_summary_absent() -> None:
    assert extract_vision_summary("plain goal without images") is None


def test_extract_vision_summary_caps_length() -> None:
    body = "x" * 5000
    text = _enriched("img", body)
    out = extract_vision_summary(text, max_chars=100)
    assert out is not None
    assert len(out) == 100
    assert out.endswith("…")


def test_merge_vision_instructions_appends() -> None:
    merged = merge_vision_instructions("- Execute the step described in EXECUTION TASK above")
    assert "EXECUTION TASK is authoritative scope" in merged
    assert "Do not expand work" in merged
    assert merged.startswith("- Execute the step")


def test_format_image_facts_for_brief() -> None:
    facts = format_image_facts_for_brief("Button labeled Submit")
    assert facts == "Image facts: Button labeled Submit"


def test_compose_execute_envelope_injects_vision_from_goal() -> None:
    from unittest.mock import MagicMock

    from soothe.sloop.engine.executor import Executor
    from soothe.sloop.state.schemas import LoopState, StepAction

    goal = _enriched(
        "Extract UI copy from the screenshot",
        "Settings page with Dark Mode toggle.",
    )
    state = LoopState(goal=goal, thread_id="t-vision", max_iterations=5)
    step = StepAction(
        id="01",
        description="Extract UI copy",
        full_description="Extract visible UI labels from the screenshot only.",
        expected_output="Label list",
    )
    envelope = Executor(MagicMock())._compose_execute_step_envelope(step, loop_state=state)
    assert "EXECUTION TASK:" in envelope
    assert "VISION CONTEXT:" in envelope
    assert "Dark Mode toggle" in envelope
    assert "GOAL:" not in envelope
    assert "Complete only this step's deliverable" in envelope
    assert "EXECUTION TASK is authoritative scope" in envelope
