"""Assess raw-text fallback bounding and salvage (loop fa03 stall)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from soothe_nano.utils.llm.structured import StructuredOutputError

from soothe.sloop.cognition import planner as planner_mod
from soothe.sloop.cognition.planner import LLMPlanner
from soothe.sloop.cognition.status_assessment_wire import coerce_status_assessment_wire_dict
from soothe.sloop.prompts import PromptBuilder


def _make_planner() -> LLMPlanner:
    model = MagicMock()
    planner = LLMPlanner.__new__(LLMPlanner)
    planner._model = model
    planner._plan_assess_model = model
    planner._plan_generate_model = model
    planner._plan_gap_model = model
    planner._config = None
    planner._loop_id = "loop-test"
    planner._prompt_builder = PromptBuilder(None)
    return planner


@pytest.mark.asyncio
async def test_assess_passes_envelope_normalizer() -> None:
    """Envelope payloads must be salvaged in-band instead of hitting the fallback."""
    planner = _make_planner()
    captured: dict[str, object] = {}

    async def _capture(*_args, **kwargs):
        captured.update(kwargs)
        raise StructuredOutputError("boom")

    with patch.object(planner_mod, "_plan_phase_chat_model", return_value=planner._model):
        planner._invoke_structured = AsyncMock(side_effect=_capture)
        planner._ainvoke_bounded = AsyncMock(return_value=AIMessage(content='{"status": "done"}'))
        await planner._assess_status_with_response(
            messages=[MagicMock()],
            goal="tidy the workspace",
            iteration=1,
            thread_id="tid",
        )

    assert captured.get("normalize") is coerce_status_assessment_wire_dict


@pytest.mark.asyncio
async def test_fallback_is_bounded_and_capped() -> None:
    """The fallback must not inherit the execute-sized 600s x 11 retry ladder."""
    planner = _make_planner()

    with patch.object(planner_mod, "_plan_phase_chat_model", return_value=planner._model):
        planner._invoke_structured = AsyncMock(side_effect=StructuredOutputError("boom"))
        planner._ainvoke_bounded = AsyncMock(
            return_value=AIMessage(content='{"status": "continue"}')
        )
        assessment, _ = await planner._assess_status_with_response(
            messages=[MagicMock()],
            goal="tidy the workspace",
            iteration=1,
            thread_id="tid",
        )

    assert assessment.status == "continue"
    planner._model.bind.assert_any_call(max_tokens=planner_mod._ASSESS_FALLBACK_MAX_TOKENS)

    policy = planner._ainvoke_bounded.await_args.kwargs["rate_limit_config"]
    assert policy.call_timeout_seconds == planner_mod._ASSESS_FALLBACK_TIMEOUT_S
    assert policy.retry_on_timeout is False
    assert policy.max_timeout_retries == 0


@pytest.mark.asyncio
async def test_fallback_recovers_tag_wrapped_yaml() -> None:
    """Loop fa03's second failure: a valid assessment emitted as tag-wrapped YAML."""
    planner = _make_planner()
    raw = AIMessage(
        content='<PLAN_ASSESS>\nstatus: "continue"\ngoal_progress: "low"\n</PLAN_ASSESS>'
    )

    with patch.object(planner_mod, "_plan_phase_chat_model", return_value=planner._model):
        planner._invoke_structured = AsyncMock(side_effect=StructuredOutputError("boom"))
        planner._ainvoke_bounded = AsyncMock(return_value=raw)
        assessment, _ = await planner._assess_status_with_response(
            messages=[MagicMock()],
            goal="tidy the workspace",
            iteration=1,
            thread_id="tid",
        )

    assert assessment.status == "continue"
    assert assessment.goal_progress == "low"
