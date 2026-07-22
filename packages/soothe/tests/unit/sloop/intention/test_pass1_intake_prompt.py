"""Tests for Pass 1 system prompt assembly."""

from __future__ import annotations

from soothe.sloop.intention.prompts import (
    INTAKE_PASS1_HUMAN_TASK,
    INTAKE_PASS1_SYSTEM_PROMPT,
    build_intake_pass1_system_prompt,
    build_prompt_timestamp_block,
)
from soothe.utils.prompt_clock import prompt_datetime_context


def test_build_prompt_timestamp_block_includes_live_values() -> None:
    block = build_prompt_timestamp_block()
    ctx = prompt_datetime_context()
    assert block.startswith("<PROMPT_TIMESTAMP>")
    assert block.endswith("</PROMPT_TIMESTAMP>")
    assert ctx["current_date"] in block
    assert ctx["current_time"] in block
    assert ctx["schedule_timezone"] in block


def test_build_intake_pass1_system_prompt_includes_identity_and_timestamp() -> None:
    prompt = build_intake_pass1_system_prompt(INTAKE_PASS1_SYSTEM_PROMPT, "Soothe")
    ctx = prompt_datetime_context()

    assert prompt.startswith("<ASSISTANT_IDENTITY>")
    assert "<PROMPT_TIMESTAMP>" in prompt
    assert ctx["current_date"] in prompt
    assert ctx["current_time"] in prompt
    assert ctx["schedule_timezone"] in prompt
    assert "<INTAKE_PASS1>" in prompt
    assert prompt.index("<ASSISTANT_IDENTITY>") < prompt.index("<INTAKE_PASS1>")
    assert prompt.index("<INTAKE_PASS1>") < prompt.index("<PROMPT_TIMESTAMP>")
    assert prompt.endswith("</PROMPT_TIMESTAMP>")


def test_build_intake_pass1_system_prompt_formats_assistant_name_in_examples() -> None:
    prompt = build_intake_pass1_system_prompt(INTAKE_PASS1_SYSTEM_PROMPT, "Soothe")

    assert "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen" in prompt
    assert "我是Soothe" in prompt
    assert "FORBIDDEN identity reply" in prompt
    assert "never output this" in prompt
    assert "(per ASSISTANT_IDENTITY)" not in prompt
    assert "{assistant_name}" not in prompt


def test_intake_pass1_human_task_avoids_identity_priming() -> None:
    assert INTAKE_PASS1_HUMAN_TASK == "Classify the user message above. JSON only."
    assert "Identity replies" not in INTAKE_PASS1_HUMAN_TASK
