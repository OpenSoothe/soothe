"""Tests for Pass 1 system prompt assembly."""

from __future__ import annotations

from soothe.foundation.sloop.intention.prompts import (
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
