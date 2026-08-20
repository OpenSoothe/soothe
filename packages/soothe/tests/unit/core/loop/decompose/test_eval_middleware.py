"""Tests for the RFC-905 readonly Eval middleware."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.sloop.eval.middleware import EvalStepMiddleware
from soothe.sloop.utils.config_keys import SOOTHE_EVAL_STEP_ID_KEY

_CONFIGURABLE = "soothe.sloop.eval.middleware._langgraph_configurable"


def _request() -> ModelRequest:
    return ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="audit")],
        system_message=SystemMessage(content="orig"),
        tools=[
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="grep"),
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


def test_eval_filters_mutating_tools_and_injects_policy() -> None:
    with patch(_CONFIGURABLE, return_value={SOOTHE_EVAL_STEP_ID_KEY: "EVAL-1"}):
        forwarded = _forward(_request())

    names = [getattr(tool, "name", None) for tool in forwarded.tools or []]
    assert names == ["read_file", "grep", "decompose_task"]
    assert "user-goal coverage audit" in forwarded.system_message.content


def test_non_eval_request_is_unchanged() -> None:
    request = _request()
    with patch(_CONFIGURABLE, return_value={}):
        forwarded = _forward(request)
    assert forwarded.tools == request.tools
