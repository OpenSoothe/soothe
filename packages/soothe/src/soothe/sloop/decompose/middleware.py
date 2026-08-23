"""Middleware: inject decompose prompts / tool on step THREADS (RFC-904).

In plan/ask modes the ``decompose_task`` tool is **stripped** from the schema
so the LLM cannot call it. A ``awrap_tool_call`` guard also intercepts any
stray ``decompose_task`` call (e.g. from a cached/forced tool choice) and
returns a guidance ``ToolMessage`` directing the LLM to finish its plan /
answer in-thread.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ContextT,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import ToolMessage

from soothe.prompts import (
    ASK_MODE_ADDENDUM,
    PARALLEL_NUDGE_ADDENDUM,
    PLAN_MODE_ADDENDUM,
    THREAD_POLICY_SYSTEM_ADDENDUM,
    WRITE_TODOS_TOOL_DESCRIPTION,
)
from soothe.sloop.decompose import runtime as _decompose_runtime
from soothe.sloop.decompose.tool import build_decompose_task_tool
from soothe.sloop.utils.config_keys import (
    SOOTHE_DECOMPOSE_STEP_ID_KEY,
    SOOTHE_EVAL_STEP_ID_KEY,
    SOOTHE_INTAKE_LABEL_KEY,
    SOOTHE_INTERACTION_MODE_KEY,
    SOOTHE_IS_DAG_ROOT_KEY,
    SOOTHE_MAX_BRANCH_ROOT_KEY,
)

logger = logging.getLogger(__name__)

_DECOMPOSE_TOOL = build_decompose_task_tool()


def _override_write_todos_description(tools: list[Any]) -> list[Any]:
    out: list[Any] = []
    for tool in tools:
        name = getattr(tool, "name", None) or getattr(tool, "get", lambda *_: None)("name")
        if name == "write_todos" and hasattr(tool, "description"):
            try:
                cloned = tool.model_copy(update={"description": WRITE_TODOS_TOOL_DESCRIPTION})
                out.append(cloned)
                continue
            except Exception:
                try:
                    tool.description = WRITE_TODOS_TOOL_DESCRIPTION
                except Exception:
                    pass
        out.append(tool)
    return out


def _ensure_decompose_tool(tools: list[Any]) -> list[Any]:
    names = {getattr(t, "name", None) for t in tools}
    if "decompose_task" in names:
        return tools
    return [*tools, _DECOMPOSE_TOOL]


def _strip_decompose_tool(tools: list[Any]) -> list[Any]:
    return [t for t in tools if getattr(t, "name", None) != "decompose_task"]


# Tools that gather evidence (search / inspection). Counting these per step
# thread lets the decompose tool handler reject proposals issued with zero
# prior grounding (d15f hallucination defense, scheme 2d). Mirrors the
# executor's search-call classification (executor.py search_calls_total).
_GROUNDING_TOOL_NAMES = frozenset({"ls", "glob", "grep", "read_file", "file_info"})


def _is_grounding_call(tool_name: str, tool_call: dict[str, Any]) -> bool:
    """True when this tool call gathers evidence (search/inspection)."""
    if tool_name in _GROUNDING_TOOL_NAMES:
        return True
    if tool_name == "run_command":
        command = str((tool_call.get("args") or {}).get("command") or "").lower()
        return any(
            marker in command
            for marker in ("grep", "rg ", "rg\n", "find ", "find\t", "ls ", "ls\n", "ls\t")
        )
    return False


def _record_evidence_if_grounding(tool_call: dict[str, Any]) -> None:
    """Increment the evidence counter when this tool call gathers evidence."""
    tool_name = str(tool_call.get("name", ""))
    if _is_grounding_call(tool_name, tool_call):
        _decompose_runtime.record_evidence_call()


class DecomposeTaskMiddleware(AgentMiddleware):
    """Inject ``decompose_task`` + THREAD policy on step threads.

    Active when a StrangeLoop step id is bound (contextvar or LangGraph
    configurable ``soothe_decompose_step_id``). Hidden on non-step threads
    (synthesis, intake specialists, etc.).

    In plan/ask modes the tool is stripped from the schema (coded policy)
    and an ``awrap_tool_call`` guard intercepts stray calls with a guidance
    message. System gets finish-vs-split / write_todos / hygiene policy +
    mode-specific addendum; user envelope stays instance-focused.
    """

    tools = [_DECOMPOSE_TOOL]

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _active_mode(conf: dict[str, Any]) -> str | None:
        """Return ``"plan"``, ``"ask"``, or ``None`` (agent) from config."""
        mode = conf.get(SOOTHE_INTERACTION_MODE_KEY)
        return mode if mode in ("plan", "ask") else None

    # ------------------------------------------------------------------
    # Tool-call guard (coded policy)
    # ------------------------------------------------------------------

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        """Intercept ``decompose_task`` in plan/ask modes.

        Even though the tool is stripped from the schema, a forced
        ``tool_choice`` or cached tool map might still route a call here.
        Return a ``ToolMessage`` that guides the LLM to finish in-thread.
        """
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        if tool_name != "decompose_task":
            # Count evidence-gathering calls so the decompose tool handler
            # can reject proposals issued with zero prior grounding.
            _record_evidence_if_grounding(tool_call)
            return await handler(request)
        conf = _decompose_runtime.langgraph_configurable()
        mode = self._active_mode(conf)
        if mode is None:
            return await handler(request)
        step_id = _decompose_runtime.current_step_id() or conf.get(
            SOOTHE_DECOMPOSE_STEP_ID_KEY, "?"
        )
        logger.info(
            "[decompose] blocked decompose_task call in %s mode (step=%s)",
            mode,
            step_id,
        )
        if mode == "plan":
            guidance = (
                "decompose_task is not available in Plan mode. "
                "Finish your research and output the plan document in this thread. "
                "Do not split into subtasks — produce the full plan now."
            )
        else:
            guidance = (
                "decompose_task is not available in Ask mode. "
                "Answer the user's question directly in this thread. "
                "Do not split into subtasks."
            )
        return ToolMessage(
            content=guidance,
            tool_call_id=tool_call.get("id", ""),
            name="decompose_task",
        )

    def wrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Any],
    ) -> Any:
        """Sync variant of the tool-call guard."""
        tool_call = getattr(request, "tool_call", None) or {}
        tool_name = str(tool_call.get("name", ""))
        if tool_name != "decompose_task":
            # Count evidence-gathering calls so the decompose tool handler
            # can reject proposals issued with zero prior grounding.
            _record_evidence_if_grounding(tool_call)
            return handler(request)
        conf = _decompose_runtime.langgraph_configurable()
        mode = self._active_mode(conf)
        if mode is None:
            return handler(request)
        step_id = _decompose_runtime.current_step_id() or conf.get(
            SOOTHE_DECOMPOSE_STEP_ID_KEY, "?"
        )
        logger.info(
            "[decompose] blocked decompose_task call in %s mode (step=%s)",
            mode,
            step_id,
        )
        if mode == "plan":
            guidance = (
                "decompose_task is not available in Plan mode. "
                "Finish your research and output the plan document in this thread. "
                "Do not split into subtasks — produce the full plan now."
            )
        else:
            guidance = (
                "decompose_task is not available in Ask mode. "
                "Answer the user's question directly in this thread. "
                "Do not split into subtasks."
            )
        return ToolMessage(
            content=guidance,
            tool_call_id=tool_call.get("id", ""),
            name="decompose_task",
        )

    # ------------------------------------------------------------------
    # Tool-set injection / system-prompt addendum
    # ------------------------------------------------------------------

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        conf = _decompose_runtime.langgraph_configurable()
        if conf.get(SOOTHE_EVAL_STEP_ID_KEY):
            # EvalStepMiddleware owns the Eval tool/prompt policy
            # (full tool surface + coverage-audit addendum + decompose_task).
            return request
        step_id = _decompose_runtime.current_step_id() or conf.get(SOOTHE_DECOMPOSE_STEP_ID_KEY)
        if not step_id:
            tools = list(request.tools or [])
            stripped = _strip_decompose_tool(tools)
            return request.override(tools=stripped) if len(stripped) != len(tools) else request

        mode = self._active_mode(conf)
        tools = list(request.tools or [])
        tools = _override_write_todos_description(tools)

        if mode in ("plan", "ask"):
            # Coded policy: strip decompose_task so the LLM can't call it.
            before = len(tools)
            tools = _strip_decompose_tool(tools)
            logger.debug(
                "[decompose] stripped decompose_task for %s mode (step=%s tools=%d→%d)",
                mode,
                step_id,
                before,
                len(tools),
            )
        else:
            # Agent mode: inject decompose_task as usual.
            before = len(tools)
            already_present = "decompose_task" in {getattr(t, "name", None) for t in tools}
            tools = _ensure_decompose_tool(tools)
            logger.debug(
                "[decompose] injecting decompose_task on step %s thread "
                "(tools=%d→%d already_present=%s)",
                step_id,
                before,
                len(tools),
                already_present,
            )

        # Build system-prompt addendum.
        addendum = THREAD_POLICY_SYSTEM_ADDENDUM
        # Inject the live max-branch-root limit so the LLM stays under cap.
        max_branch_root = conf.get(SOOTHE_MAX_BRANCH_ROOT_KEY)
        if isinstance(max_branch_root, int) and max_branch_root > 0:
            addendum = (
                f"{addendum}\n\n"
                f"## decompose_task subtask limit\n\n"
                f"Propose at most {max_branch_root} child subtasks per "
                f"decompose_task call. If the work needs more, group related "
                f"items into fewer broader subtasks (each can decompose "
                f"further in its own thread). Exceeding {max_branch_root} "
                f"subtasks causes the proposal to be rejected."
            )
        if mode == "ask":
            addendum = f"{addendum}\n\n{ASK_MODE_ADDENDUM}"
        elif mode == "plan":
            addendum = f"{addendum}\n\n{PLAN_MODE_ADDENDUM}"
        else:
            # Agent mode: soft parallelization nudge for complex root steps.
            # Fires only on a DAG root (never child steps — prevents recursive
            # fan-out nudging at every decompose layer) when the intake LLM
            # classified the goal as complex ("multi-phase / parallel
            # workstreams"). Language-independent semantic signal — no keyword
            # matching. Soft, not mandatory: the LLM is invited to *assess*
            # parallelization, not forced to split (avoids the
            # DECOMPOSE_FIRST_HINT pass-through chain regression).
            is_root = conf.get(SOOTHE_IS_DAG_ROOT_KEY) is True
            intake_label = conf.get(SOOTHE_INTAKE_LABEL_KEY)
            if is_root and isinstance(intake_label, str) and intake_label.lower() == "complex":
                addendum = f"{addendum}\n\n{PARALLEL_NUDGE_ADDENDUM}"

        system = request.system_message
        if system is not None and hasattr(system, "content"):
            content = system.content
            if isinstance(content, str) and addendum not in content:
                from langchain_core.messages import SystemMessage

                new_system = SystemMessage(content=f"{content}\n\n{addendum}")
                return request.override(tools=tools, system_message=new_system)
            if isinstance(content, list):
                from langchain_core.messages import SystemMessage

                new_blocks = [
                    *content,
                    {"type": "text", "text": f"\n\n{addendum}"},
                ]
                new_system = SystemMessage(content=new_blocks)
                return request.override(tools=tools, system_message=new_system)

        return request.override(tools=tools)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Apply decompose injection before the sync model call."""
        return handler(self.modify_request(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Apply decompose injection before the async model call."""
        return await handler(self.modify_request(request))
