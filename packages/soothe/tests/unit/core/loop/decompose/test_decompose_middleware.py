"""Tests for DecomposeTaskMiddleware tool injection (IG-751)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.sloop.decompose.runtime import bind_decompose_runtime, reset_decompose_runtime
from soothe.sloop.middleware import DecomposeTaskMiddleware
from soothe.sloop.utils.config_keys import SOOTHE_DECOMPOSE_STEP_ID_KEY

_CONFIGURABLE = "soothe.sloop.decompose.middleware._langgraph_configurable"


def _request() -> ModelRequest:
    return ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="do the work")],
        system_message=SystemMessage(content="orig"),
        tools=[SimpleNamespace(name="read_file")],
        state={},
    )


def _tool_names(request: ModelRequest) -> list[str]:
    return [getattr(t, "name", None) for t in (request.tools or [])]


def _run_through_hook(middleware: DecomposeTaskMiddleware, request: ModelRequest) -> ModelRequest:
    """Drive the real langchain hook so a dead hook name fails the test."""
    seen: dict[str, ModelRequest] = {}

    async def handler(req: ModelRequest) -> str:
        seen["request"] = req
        return "response"

    asyncio.run(middleware.awrap_model_call(request, handler))
    return seen["request"]


def test_awrap_model_call_injects_decompose_tool() -> None:
    sink: list = []
    tokens = bind_decompose_runtime(step_id="AAA-01", sink=sink)
    try:
        with patch(_CONFIGURABLE, return_value={}):
            forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    finally:
        reset_decompose_runtime(tokens)

    assert "decompose_task" in _tool_names(forwarded)
    content = forwarded.system_message.content
    assert "This thread: finish vs split" in content
    assert "write_todos (this thread only)" in content


def test_injection_uses_configurable_step_id_without_contextvar() -> None:
    conf = {SOOTHE_DECOMPOSE_STEP_ID_KEY: "BBB-02"}
    with patch(_CONFIGURABLE, return_value=conf):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())

    assert "decompose_task" in _tool_names(forwarded)


def test_no_injection_without_step_binding() -> None:
    with patch(_CONFIGURABLE, return_value={}):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())

    assert "decompose_task" not in _tool_names(forwarded)


def test_registered_tool_is_hidden_on_ungated_threads() -> None:
    """Registered middleware tools reach every request; step gate must hide them."""
    base = _request()
    request = base.override(tools=[*(base.tools or []), *DecomposeTaskMiddleware.tools])

    with patch(_CONFIGURABLE, return_value={}):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), request)

    assert "decompose_task" not in _tool_names(forwarded)


def test_tool_is_registered_for_the_agent_tool_node() -> None:
    """Without registration the tool node rejects the call at execution time."""
    assert [getattr(t, "name", None) for t in DecomposeTaskMiddleware.tools] == ["decompose_task"]
