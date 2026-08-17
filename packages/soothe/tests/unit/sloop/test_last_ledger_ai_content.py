"""Tests for ``last_ledger_ai_content`` phase exclusion (RFC-214, RFC-222 §Goal-Report-Pair).

Preamble AI turns (ancestor goal-report pairs) must not be surfaced as final
user-facing output in ``ledger_direct`` completion mode — they are context,
not the current goal's answer.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage, last_ledger_ai_content


def _state_with(messages: list[Any]) -> Any:
    state = MagicMock()
    state.loop_messages = messages
    return state


class TestLastLedgerAIContent:
    def test_preamble_ai_turn_excluded(self) -> None:
        """A preamble AI turn must not be returned as the final output."""
        state = _state_with(
            [
                LoopHumanMessage(content="ancestor directive", phase="preamble"),
                LoopAIMessage(content="ancestor report", phase="preamble"),
                LoopHumanMessage(content="current goal", phase="intake"),
            ]
        )
        # No execute-step AI message → empty (preamble excluded).
        assert last_ledger_ai_content(state) == ""

    def test_preamble_not_surfaces_over_real_output(self) -> None:
        state = _state_with(
            [
                LoopAIMessage(content="ancestor report", phase="preamble"),
                LoopAIMessage(content="real step output", phase="execute_step"),
            ]
        )
        assert last_ledger_ai_content(state) == "real step output"

    def test_intake_phase_still_excluded(self) -> None:
        state = _state_with(
            [
                LoopAIMessage(content="intake reasoning", phase="intake"),
            ]
        )
        assert last_ledger_ai_content(state) == ""
