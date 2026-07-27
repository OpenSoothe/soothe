"""Unit tests for IG-653 plan-phase timing log helpers."""

from __future__ import annotations

import logging

from soothe.sloop.cognition.planner import (
    _log_plan_phase_timing,
    _prompt_chars_for_messages,
)


def test_prompt_chars_for_messages_sums_content() -> None:
    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    assert _prompt_chars_for_messages([_Msg("abc"), _Msg("de")]) == 5


def test_log_plan_phase_timing_format(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="soothe.sloop.cognition.planner"):
        _log_plan_phase_timing(
            phase="gap",
            elapsed_ms=3120.4,
            prompt_chars=8400,
            iteration=2,
        )
        _log_plan_phase_timing(
            phase="generate",
            elapsed_ms=5010.0,
            prompt_chars=1200,
            iteration=0,
            lightweight=True,
        )

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        m.startswith("[Plan] phase=gap elapsed_ms=3120 prompt_chars=8400 iter=2") for m in messages
    )
    assert any(
        m.startswith(
            "[Plan] phase=generate elapsed_ms=5010 prompt_chars=1200 iter=0 lightweight=true"
        )
        for m in messages
    )
