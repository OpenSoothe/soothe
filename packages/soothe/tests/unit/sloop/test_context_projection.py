"""Unit tests for unified loop-context projection (LoopContextProjector)."""

from __future__ import annotations

from soothe.sloop.context_projection import (
    LoopContextProjector,
    ProjectionSpec,
    project_preamble_messages,
)
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def _msg(phase: str, content: str, *, ai: bool = False) -> LoopHumanMessage | LoopAIMessage:
    cls = LoopAIMessage if ai else LoopHumanMessage
    return cls(content=content, phase=phase)


def test_project_preamble_messages_filters_and_caps_turns() -> None:
    ledger = [
        _msg("preamble", "ancestor user 1"),
        _msg("preamble", "ancestor ai 1", ai=True),
        _msg("preamble", "ancestor user 2"),
        _msg("preamble", "ancestor ai 2", ai=True),
        _msg("execute_step", "not preamble"),
    ]
    # max_turns=1 → last turn only (2 messages)
    out = project_preamble_messages(ledger, max_turns=1)
    assert [m.content for m in out] == ["ancestor user 2", "ancestor ai 2"]


def test_project_preamble_messages_disabled_when_zero() -> None:
    ledger = [_msg("preamble", "ancestor user")]
    assert project_preamble_messages(ledger, max_turns=0) == []


def test_synthesis_includes_preamble_and_prior_goal() -> None:
    ledger = [
        _msg("preamble", "ancestor user"),
        _msg("preamble", "ancestor ai", ai=True),
        _msg("goal_completion", "finalize"),
        _msg("goal_completion", "synthesized report", ai=True),
        _msg("execute_step", "step"),
        _msg("execute_step", "step output", ai=True),
    ]
    projector = LoopContextProjector(config=None)
    projected = projector.project(ledger, ProjectionSpec(phase="synthesis"))
    contents = [m.content for m in projected.messages]
    assert "ancestor user" in contents
    assert "synthesized report" in contents


def test_intake_includes_preamble() -> None:
    ledger = [
        _msg("preamble", "ancestor user"),
        _msg("preamble", "ancestor ai", ai=True),
    ]
    projector = LoopContextProjector(config=None)
    projected = projector.project(ledger, ProjectionSpec(phase="intake"))
    assert [m.content for m in projected.messages] == ["ancestor user", "ancestor ai"]
