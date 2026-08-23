"""Tests for the RFC-905 coverage-audit Eval middleware."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware.types import ModelRequest, ToolCallRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.sloop.middleware import EvalStepMiddleware
from soothe.sloop.utils.config_keys import SOOTHE_EVAL_STEP_ID_KEY

_CONFIGURABLE = "soothe.sloop.decompose.runtime.langgraph_configurable"


def _request() -> ModelRequest:
    return ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="audit")],
        system_message=SystemMessage(content="orig"),
        tools=[
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="grep"),
            SimpleNamespace(name="glob"),
            SimpleNamespace(name="ls"),
            SimpleNamespace(name="list_files"),
            SimpleNamespace(name="file_info"),
            SimpleNamespace(name="write_file"),
            SimpleNamespace(name="execute"),
            SimpleNamespace(name="task"),
        ],
        state={},
    )


def _forward(request: ModelRequest) -> ModelRequest:
    seen: dict[str, ModelRequest] = {}

    async def handler(req: ModelRequest) -> str:
        seen["request"] = req
        return "ok"

    asyncio.run(EvalStepMiddleware().awrap_model_call(request, handler))
    return seen["request"]


def test_eval_keeps_full_tool_surface_and_injects_policy() -> None:
    with patch(_CONFIGURABLE, return_value={SOOTHE_EVAL_STEP_ID_KEY: "EVAL-1"}):
        forwarded = _forward(_request())

    names = [getattr(tool, "name", None) for tool in forwarded.tools or []]
    # Eval threads keep the full tool surface (verification commands included);
    # decompose_task is ensured as the continuation-proposal escape hatch.
    assert "write_file" in names
    assert "execute" in names
    assert "task" in names
    assert "read_file" in names
    assert "decompose_task" in names
    assert "user-goal coverage audit" in forwarded.system_message.content


def test_non_eval_request_is_unchanged() -> None:
    request = _request()
    with patch(_CONFIGURABLE, return_value={}):
        forwarded = _forward(request)
    assert forwarded.tools == request.tools


@pytest.mark.asyncio
async def test_eval_tool_call_permits_mutating_tool() -> None:
    """Eval threads no longer fail-closed on mutating tools — the auditor must be
    able to run verification commands (write/exec) to confirm goal achievement."""
    request = ToolCallRequest(
        tool_call={"id": "call-1", "name": "write_file", "args": {}},
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    handler_called = False

    async def handler(_request: ToolCallRequest) -> str:
        nonlocal handler_called
        handler_called = True
        return "mutated"

    configurable = {SOOTHE_EVAL_STEP_ID_KEY: "EVAL-1"}
    with patch(_CONFIGURABLE, return_value=configurable):
        result = await EvalStepMiddleware().awrap_tool_call(request, handler)

    assert handler_called is True
    assert result == "mutated"
