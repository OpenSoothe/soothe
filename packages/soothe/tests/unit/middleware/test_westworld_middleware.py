"""Tests for WestWorldMiddleware (phrase-triggered agent behavior)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.prompts import WESTWORLD_FANOUT_ADDENDUM
from soothe.sloop.middleware import WestWorldMiddleware
from soothe.sloop.utils.config_keys import (
    SOOTHE_DECOMPOSE_STEP_ID_KEY,
    SOOTHE_EVAL_STEP_ID_KEY,
    SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY,
    SOOTHE_INTERACTION_MODE_KEY,
)


def _run_through_hook(middleware: object, request: ModelRequest) -> ModelRequest:
    """Drive the real langchain hook so a dead hook name fails the test."""
    seen: dict[str, ModelRequest] = {}

    async def handler(req: ModelRequest) -> str:
        seen["request"] = req
        return "response"

    awrap = getattr(middleware, "awrap_model_call")
    asyncio.run(awrap(request, handler))
    return seen["request"]


def _make_request(
    messages: list,
    *,
    system_content: str = "orig",
) -> ModelRequest:
    return ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=messages,
        system_message=SystemMessage(content=system_content),
        tools=[SimpleNamespace(name="decompose_task")],
        state={},
    )


def _configurable(**kwargs: object) -> dict:
    """Build a configurable dict with the given keys, always including thread_id."""
    return {"configurable": {"thread_id": "t1", **kwargs}}


# ── Trigger fires ──────────────────────────────────────────────────────────


def test_phrase_in_last_human_message_triggers_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams the landing page")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM in modified.system_message.content


def test_case_insensitive_substring_match() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="Please Fan Out Beams now")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM in modified.system_message.content


def test_fan_out_subagents_triggers_same_addendum() -> None:
    """The ``fan out subagents`` phrase must fire the same addendum as
    ``fan out beams`` (same effect, alternate phrasing)."""
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out subagents the goal")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM in modified.system_message.content


def test_fan_out_subagents_case_insensitive() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="Please Fan Out Subagents now")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM in modified.system_message.content


# ── No trigger ─────────────────────────────────────────────────────────────


def test_no_phrase_no_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="build the landing page")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert modified.system_message.content == "orig"


def test_phrase_in_history_not_last_human_no_trigger() -> None:
    """A phrase in a projected (non-last) HumanMessage must NOT trigger.

    This prevents child-step threads (which may project the root envelope in
    history) from recursively re-triggering fan-out.
    """
    middleware = WestWorldMiddleware()
    request = _make_request(
        [
            HumanMessage(content="fan out beams the goal"),
            AIMessage(content="decomposing"),
            HumanMessage(content="child task: implement button"),
        ]
    )
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "child-1"}),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM not in modified.system_message.content


# ── Guard skips ────────────────────────────────────────────────────────────


def test_no_step_id_no_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch("langgraph.config.get_config", return_value=_configurable()):
        modified = _run_through_hook(middleware, request)
    assert modified.system_message.content == "orig"


def test_plan_mode_skips_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(
            **{
                SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1",
                SOOTHE_INTERACTION_MODE_KEY: "plan",
            }
        ),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM not in modified.system_message.content


def test_ask_mode_skips_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(
            **{
                SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1",
                SOOTHE_INTERACTION_MODE_KEY: "ask",
            }
        ),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM not in modified.system_message.content


def test_eval_step_skips_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(
            **{
                SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1",
                SOOTHE_EVAL_STEP_ID_KEY: "eval-1",
            }
        ),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM not in modified.system_message.content


def test_goal_synthesis_skips_addendum() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(
            **{
                SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1",
                SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY: True,
            }
        ),
    ):
        modified = _run_through_hook(middleware, request)
    assert WESTWORLD_FANOUT_ADDENDUM not in modified.system_message.content


# ── Idempotency ────────────────────────────────────────────────────────────


def test_modify_request_idempotent() -> None:
    middleware = WestWorldMiddleware()
    request = _make_request([HumanMessage(content="fan out beams")])
    with patch(
        "langgraph.config.get_config",
        return_value=_configurable(**{SOOTHE_DECOMPOSE_STEP_ID_KEY: "step-1"}),
    ):
        once = _run_through_hook(middleware, request)
        # Run again on the already-modified request.
        twice = _run_through_hook(middleware, once)
    assert twice.system_message.content.count(WESTWORLD_FANOUT_ADDENDUM) == 1


# ── Evidence-first wording (self-hygiene guidance) ────────────────────────


def test_fanout_addendum_requires_evidence_before_decompose() -> None:
    """The fan-out addendum must recommend gathering evidence before calling
    decompose_task (self-hygiene: decomposing without grounding wastes
    child-thread budget when the model fabricates non-existent areas)."""
    text = WESTWORLD_FANOUT_ADDENDUM.lower()
    assert "evidence" in text or "confirm" in text
    assert any(w in text for w in ("ls", "glob", "grep", "read_file", "search"))
    # Must NOT contain the old unconditional "before doing any other work" order.
    assert "before doing any other work" not in text


def test_fanout_addendum_has_evidence_cap_and_stuck_guard() -> None:
    """The fan-out addendum must cap evidence gathering and include a stuck
    guard so the model does not loop on read-only calls forever."""
    text = WESTWORLD_FANOUT_ADDENDUM.lower()
    assert "~5" in text or "5 evidence" in text
    assert "stuck" in text
    # Must offer an "execute directly" escape when decompose is not called.
    assert "execute" in text or "directly" in text
