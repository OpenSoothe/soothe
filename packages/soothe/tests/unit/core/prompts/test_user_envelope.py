"""Tests for RFC-214 user message envelopes."""

from __future__ import annotations

from soothe.core.prompts.user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)


def test_execute_envelope_includes_response_language_hint() -> None:
    envelope = build_execute_step_envelope(
        goal="请总结项目",
        step_description="Read README",
        execution_hints=None,
        iteration=1,
        max_iterations=3,
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope
    assert "<CONTEXT_INFO>" in envelope


def test_plan_context_envelope_includes_response_language_hint() -> None:
    envelope = build_plan_context_envelope(
        goal="Résumé demandé",
        iteration=1,
        max_iterations=5,
    )
    assert "<response_language_hint>" in envelope
    assert "same natural language as the user's goal" in envelope
