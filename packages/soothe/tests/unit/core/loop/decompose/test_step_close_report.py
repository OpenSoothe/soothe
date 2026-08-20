"""Safety fallbacks for structured action close assessment."""

from __future__ import annotations

import pytest

from soothe.sloop.eval.step_close_report import assess_step_close


@pytest.mark.asyncio
async def test_missing_fast_model_requires_eval() -> None:
    report = await assess_step_close(
        fast_model=None,
        user_goal="finish the migration",
        step_description="migrate the database",
        final_output="partial result",
        outcome_summary={},
    )

    assert report.goal_portion_complete is False
    assert report.early_exit is True
    assert report.requires_eval is True
