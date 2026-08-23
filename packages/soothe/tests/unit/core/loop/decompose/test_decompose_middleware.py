"""Tests for DecomposeTaskMiddleware tool injection (IG-751)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe.prompts import PARALLEL_NUDGE_ADDENDUM
from soothe.sloop.decompose.runtime import bind_decompose_runtime, reset_decompose_runtime
from soothe.sloop.middleware import DecomposeTaskMiddleware
from soothe.sloop.utils.config_keys import (
    SOOTHE_DECOMPOSE_STEP_ID_KEY,
    SOOTHE_INTAKE_LABEL_KEY,
    SOOTHE_INTERACTION_MODE_KEY,
    SOOTHE_IS_DAG_ROOT_KEY,
)

_CONFIGURABLE = "soothe.sloop.decompose.runtime.langgraph_configurable"


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


# ── Soft parallelization nudge (complex root steps) ─────────────────────────


def _root_conf(intake_label: str | None = "complex") -> dict:
    """Configurable for a root step with the given intake label."""
    conf: dict = {SOOTHE_DECOMPOSE_STEP_ID_KEY: "ROOT-01", SOOTHE_IS_DAG_ROOT_KEY: True}
    if intake_label is not None:
        conf[SOOTHE_INTAKE_LABEL_KEY] = intake_label
    return conf


def test_complex_root_step_gets_parallel_nudge() -> None:
    with patch(_CONFIGURABLE, return_value=_root_conf("complex")):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM in forwarded.system_message.content


def test_simple_root_step_no_nudge() -> None:
    with patch(_CONFIGURABLE, return_value=_root_conf("simple")):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_minimal_root_step_no_nudge() -> None:
    with patch(_CONFIGURABLE, return_value=_root_conf("minimal")):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_child_step_no_nudge_even_if_complex() -> None:
    """is_dag_root guard: child steps must not get the nudge (no recursion)."""
    conf = _root_conf("complex")
    conf[SOOTHE_IS_DAG_ROOT_KEY] = False
    with patch(_CONFIGURABLE, return_value=conf):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_root_step_without_intake_label_no_nudge() -> None:
    with patch(_CONFIGURABLE, return_value=_root_conf(None)):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_plan_mode_suppresses_nudge_even_if_complex_root() -> None:
    conf = _root_conf("complex")
    conf[SOOTHE_INTERACTION_MODE_KEY] = "plan"
    with patch(_CONFIGURABLE, return_value=conf):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_ask_mode_suppresses_nudge_even_if_complex_root() -> None:
    conf = _root_conf("complex")
    conf[SOOTHE_INTERACTION_MODE_KEY] = "ask"
    with patch(_CONFIGURABLE, return_value=conf):
        forwarded = _run_through_hook(DecomposeTaskMiddleware(), _request())
    assert PARALLEL_NUDGE_ADDENDUM not in forwarded.system_message.content


def test_nudge_prefers_fanout_but_allows_finish_exception() -> None:
    """Nudge prefers parallel fan-out (dominant signal) with a narrow finish
    exception. Regression guard: must NOT use unconditional mandatory language
    ('must' / 'before doing any work') that caused the DECOMPOSE_FIRST_HINT
    pass-through chain; instead it frames fan-out as preferred with an
    explicit cohesion escape hatch."""
    nudge = PARALLEL_NUDGE_ADDENDUM
    # Dominant signal: fan-out is the preferred path.
    assert "prefer" in nudge.lower()
    assert "decompose_task" in nudge
    # Escape hatch: finish-in-thread is allowed for cohesive work.
    assert "cohesive" in nudge.lower() or "single" in nudge.lower()
    # Regression guard: no unconditional mandatory split language.
    assert "must" not in nudge.lower()
    # 'NOW' is allowed only in the conditional fan-out branch, not as an
    # unconditional order — verify it sits inside a "when you see" clause.
    if "now" in nudge.lower():
        assert "when" in nudge.lower() or "if" in nudge.lower()
    # Evidence-first: the nudge must require gathering evidence before fan-out
    # (d15f hallucination defense — decomposing without grounding fabricated
    # non-existent client dirs).
    assert any(word in nudge.lower() for word in ("evidence", "confirm", "ls", "glob", "grep")), (
        "nudge must require gathering evidence before decompose"
    )


def test_nudge_idempotent_on_repeat_hook() -> None:
    """Running the hook twice on the same request must not duplicate the nudge."""
    with patch(_CONFIGURABLE, return_value=_root_conf("complex")):
        once = _run_through_hook(DecomposeTaskMiddleware(), _request())
        twice = _run_through_hook(DecomposeTaskMiddleware(), once)
    assert twice.system_message.content.count(PARALLEL_NUDGE_ADDENDUM) == 1
