"""Tests for goal-completion output reconciliation (IG-578)."""

from __future__ import annotations

from soothe.sloop.engine.goal_completion_output import (
    collect_execute_step_deliverable_text,
    reconcile_synthesis_with_step_ledger,
    synthesis_reflects_step_deliverables,
)
from soothe.sloop.utils.messages import LoopAIMessage


def test_collect_execute_step_deliverable_text() -> None:
    messages = [
        LoopAIMessage(content="**Total file count in packages: 3632**", phase="execute_step"),
        LoopAIMessage(content="final synthesis", phase="goal_completion"),
    ]
    assert (
        collect_execute_step_deliverable_text(messages) == "**Total file count in packages: 3632**"
    )


def test_synthesis_reflects_step_deliverables_requires_numeric_overlap() -> None:
    deliverable = "**Total file count in packages: 3632**"
    good = "There are 3632 files under packages."
    bad = "I'll count all files in the packages directory. Let me explore the workspace."
    assert synthesis_reflects_step_deliverables(good, deliverable) is True
    assert synthesis_reflects_step_deliverables(bad, deliverable) is False


def test_reconcile_prefers_step_deliverable_when_synthesis_drifts() -> None:
    messages = [
        LoopAIMessage(content="**Total file count in packages: 3632**", phase="execute_step"),
    ]
    drifted = "I'll count all files in the packages directory. Let me explore the workspace."
    assert (
        reconcile_synthesis_with_step_ledger(drifted, loop_messages=messages)
        == "**Total file count in packages: 3632**"
    )


def test_reconcile_keeps_good_synthesis() -> None:
    messages = [
        LoopAIMessage(content="**Total file count in packages: 3632**", phase="execute_step"),
    ]
    good = "The packages tree contains 3632 files."
    assert reconcile_synthesis_with_step_ledger(good, loop_messages=messages) == good
