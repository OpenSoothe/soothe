"""Tests for between-wave step brief hydration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.loop.engine.step_brief_hydrator import StepBriefHydration, StepBriefHydrator
from soothe.foundation.loop.state.schemas import StepAction


@pytest.mark.asyncio
async def test_hydrator_uses_template_when_model_unavailable() -> None:
    step = StepAction(
        id="02",
        description="Fix identified failures",
        dependencies=["01"],
    )
    hydrator = StepBriefHydrator(None, None)
    result = await hydrator.hydrate(
        step,
        predecessor_evidence="Step 01 — verify\n---\n✗ lint in foo.py",
        goal="fix repo",
    )
    assert "Do NOT repeat discovery" in result
    assert "lint in foo.py" in result


@pytest.mark.asyncio
async def test_hydrator_uses_llm_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    step = StepAction(
        id="02",
        description="Fix identified failures",
        dependencies=["01"],
    )
    model = MagicMock()
    hydrator = StepBriefHydrator(model, None)

    async def _fake_invoke(*_args, **_kwargs):
        return StepBriefHydration(
            full_description=(
                "Edit foo.py to resolve the lint error reported in step 01. "
                "Do not re-run verify_finally.sh until the edit is complete."
            )
        )

    monkeypatch.setattr(
        "soothe.foundation.loop.engine.step_brief_hydrator.invoke_structured_chat_typed",
        _fake_invoke,
    )

    result = await hydrator.hydrate(
        step,
        predecessor_evidence="Step 01 — verify\n---\n✗ lint in foo.py",
        goal="fix repo",
    )
    assert "Do not re-run verify_finally.sh" in result
