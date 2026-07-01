"""Unit tests for the clarification policy selector."""

from __future__ import annotations

import pytest
from soothe.foundation.sloop.clarification.auto import AutoClarificationPolicy
from soothe.foundation.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.foundation.sloop.clarification.protocol import ClarificationRequest
from soothe.foundation.sloop.clarification.selector import build_default_clarification_policy

from soothe.subagents.veritas.schemas import VeritasAnswerSchema


async def _stub_veritas(_req: ClarificationRequest) -> VeritasAnswerSchema:
    return VeritasAnswerSchema(answers=["x"], confidence=0.9)


def test_manual_returns_interactive() -> None:
    policy = build_default_clarification_policy("manual")
    assert isinstance(policy, InteractiveClarificationPolicy)


def test_auto_returns_auto_policy() -> None:
    policy = build_default_clarification_policy("auto", veritas_answer=_stub_veritas)
    assert isinstance(policy, AutoClarificationPolicy)


def test_auto_requires_veritas_callable() -> None:
    with pytest.raises(ValueError):
        build_default_clarification_policy("auto")


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError):
        build_default_clarification_policy("garbage")  # type: ignore[arg-type]


def test_auto_passes_min_confidence_through() -> None:
    policy = build_default_clarification_policy(
        "auto", veritas_answer=_stub_veritas, min_confidence=0.75
    )
    assert isinstance(policy, AutoClarificationPolicy)
    assert policy.min_confidence == pytest.approx(0.75)
