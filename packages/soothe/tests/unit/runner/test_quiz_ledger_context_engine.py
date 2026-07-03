"""Tests for quiz ledger persistence via active loop ContextEngine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.runner._runner_phases import PhasesMixin


class _QuizLedgerRunner(PhasesMixin):
    def __init__(self) -> None:
        self._config = MagicMock()
        self._client_loop_id_for_stream = "loop-1"


@pytest.mark.asyncio
async def test_save_quiz_to_ledger_uses_provided_context_engine() -> None:
    runner = _QuizLedgerRunner()
    ce = MagicMock()
    ce.save = AsyncMock()

    with patch(
        "soothe.foundation.sloop.utils.messages._record_ledger_message",
    ) as record:
        await runner._save_quiz_to_ledger(
            "hello",
            "Hi there!",
            "thread-1",
            context_engine=ce,
        )

    assert record.call_count == 2
    ce.save.assert_awaited_once()
