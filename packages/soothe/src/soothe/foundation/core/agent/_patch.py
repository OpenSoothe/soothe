"""Runtime compatibility patches.

Patches are applied at import time and isolated from CoreAgent logic.
These patches fix upstream issues that affect Soothe's execution.

Note: Do not enable PEP 563 (``from __future__ import annotations``) in this module.
``StructuredTool._injected_args_keys`` uses ``inspect.signature`` and
``_is_injected_arg_type(parameter.annotation)``. String annotations would prevent
``ToolRuntime`` from being recognized, so ``runtime`` would be stripped during
Pydantic validation and the task tool would fail at runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Annotated, Any

logger = logging.getLogger(__name__)

_TOOLS_TOKEN_CACHE: dict[str, int] = {}
_SOOTHE_SUMMARIZATION_TOKEN_PATCHED = "_soothe_summarization_token_count_patched"

# Used in patched ``task`` / ``atask`` signatures so LangGraph detects injection.
try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at lint import time
    ToolRuntime = Any  # type: ignore[misc,assignment]


def _patch_summarization_overwrite_handling() -> None:
    """Patch SummarizationMiddleware for Overwrite wrapper handling.

    SummarizationMiddleware._apply_event_to_messages does not
    handle langgraph's Overwrite wrapper that PatchToolCallsMiddleware may
    leave in request.messages. This patch unwraps it so ``list(messages)`` succeeds.

    This is a temporary workaround until fixed upstream.
    """
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from langgraph.types import Overwrite
    except ImportError:
        return

    _original = SummarizationMiddleware._apply_event_to_messages

    @staticmethod  # type: ignore[misc]
    def _patched(messages: Any, event: Any) -> list[Any]:
        if isinstance(messages, Overwrite):
            messages = messages.value
        return _original(messages, event)

    SummarizationMiddleware._apply_event_to_messages = _patched  # type: ignore[assignment]


def _tools_token_cache_key(tools: list[Any] | None) -> str | None:
    """Build a stable cache key for a tool list."""
    if not tools:
        return None
    parts: list[str] = []
    for tool in tools:
        if isinstance(tool, dict):
            parts.append(json.dumps(tool, sort_keys=True, default=str))
        else:
            name = getattr(tool, "name", None) or ""
            description = getattr(tool, "description", None) or ""
            parts.append(f"{name}:{description}")
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[:32]


def _messages_token_cache_key(messages: Iterable[Any]) -> str:
    """Build a lightweight cache key for message lists."""
    parts: list[str] = []
    for message in messages:
        if message is None:
            parts.append("none")
            continue
        message_id = getattr(message, "id", None) or id(message)
        content = getattr(message, "content", "")
        if isinstance(content, str):
            content_len = len(content)
        elif isinstance(content, list):
            content_len = sum(len(str(block)) for block in content)
        else:
            content_len = len(str(content))
        tool_calls = getattr(message, "tool_calls", None) or ()
        parts.append(f"{message_id}:{content_len}:{len(tool_calls)}")
    return "|".join(parts)


def _cached_tools_token_count(
    token_counter: Any,
    tools: list[Any] | None,
) -> int:
    """Count tool schema tokens once per unique tool set."""
    cache_key = _tools_token_cache_key(tools)
    if cache_key is None:
        return 0
    cached = _TOOLS_TOKEN_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        count = token_counter([], tools=tools)
    except TypeError:
        count = 0
    _TOOLS_TOKEN_CACHE[cache_key] = count
    return count


def _split_conversation_token_count(
    token_counter: Any,
    messages: Iterable[Any],
    tools: list[Any] | None,
) -> int:
    """Count message and tool tokens separately; cache tool schemas globally."""
    tools_tokens = _cached_tools_token_count(token_counter, tools)
    try:
        message_tokens = token_counter(messages, tools=None)
    except TypeError:
        message_tokens = token_counter(messages)
    return tools_tokens + message_tokens


def _patch_summarization_token_count_optimization() -> None:
    """Speed up SummarizationMiddleware pre-model token counting.

    Upstream ``awrap_model_call`` counts tokens twice per model call (in
    ``_truncate_args`` and again before ``_should_summarize``), and each count
    re-serializes every tool schema. For large tool sets this dominates the
    Langfuse ``model`` span gap (~12s in recent loops).
    """
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
    except ImportError:
        return

    if getattr(SummarizationMiddleware, _SOOTHE_SUMMARIZATION_TOKEN_PATCHED, False):
        return

    _original_init = SummarizationMiddleware.__init__
    _original_truncate_args = SummarizationMiddleware._truncate_args
    _original_wrap_model_call = SummarizationMiddleware.wrap_model_call
    _original_awrap_model_call = SummarizationMiddleware.awrap_model_call

    def _wrap_token_counter(self: Any, token_counter: Any) -> Any:
        def wrapped_counter(
            messages: Iterable[Any],
            tools: list[Any] | None = None,
        ) -> int:
            per_call_cache = getattr(self, "_soothe_token_count_cache", None)
            cache_key = (_messages_token_cache_key(messages), _tools_token_cache_key(tools))
            if per_call_cache is not None and cache_key in per_call_cache:
                return per_call_cache[cache_key]

            total = _split_conversation_token_count(token_counter, messages, tools)
            if per_call_cache is not None:
                per_call_cache[cache_key] = total
            return total

        return wrapped_counter

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        _original_init(self, *args, **kwargs)
        original_counter = self._lc_helper.token_counter
        self._lc_helper.token_counter = _wrap_token_counter(self, original_counter)

    def patched_truncate_args(
        self: Any,
        messages: list[Any],
        system_message: Any,
        tools: list[Any] | None,
    ) -> tuple[list[Any], bool]:
        truncate_trigger = getattr(self, "_truncate_args_trigger", None)
        if truncate_trigger is not None:
            trigger_type, trigger_value = truncate_trigger
            if trigger_type == "messages" and len(messages) < trigger_value:
                return messages, False

        return _original_truncate_args(self, messages, system_message, tools)

    def patched_wrap_model_call(self: Any, request: Any, handler: Any) -> Any:
        self._soothe_token_count_cache = {}
        try:
            return _original_wrap_model_call(self, request, handler)
        finally:
            self._soothe_token_count_cache = {}

    async def patched_awrap_model_call(self: Any, request: Any, handler: Any) -> Any:
        self._soothe_token_count_cache = {}
        try:
            return await _original_awrap_model_call(self, request, handler)
        finally:
            self._soothe_token_count_cache = {}

    SummarizationMiddleware.__init__ = patched_init  # type: ignore[method-assign]
    SummarizationMiddleware._truncate_args = patched_truncate_args  # type: ignore[method-assign]
    SummarizationMiddleware.wrap_model_call = patched_wrap_model_call  # type: ignore[method-assign]
    SummarizationMiddleware.awrap_model_call = patched_awrap_model_call  # type: ignore[method-assign]
    setattr(SummarizationMiddleware, _SOOTHE_SUMMARIZATION_TOKEN_PATCHED, True)


def _patch_task_tool_propagates_parent_runnable_config() -> None:
    """Propagate parent ``ToolRuntime.config`` into subagent ``invoke`` / ``ainvoke``.

    Upstream ``task`` tool calls ``subagent.ainvoke(subagent_state)``
    without config. Nested compiled graphs then get LangGraph's no-op
    ``stream_writer``, so ``get_stream_writer()`` in subagent nodes does not
    forward ``emit_progress()`` custom events to the main agent stream.

    Passes the tool's ``runtime.config`` so nested runs share the parent's streaming
    runtime (fixes CLI/TUI capability step events for browser and similar).

    The ``runtime`` parameter must stay annotated as ``ToolRuntime`` (not ``Any``) so
    LangGraph's tool node injects it; see ``_get_all_injected_args`` in tool_node.
    """
    try:
        from deepagents.middleware import subagents as sm
        from langchain_core.messages import HumanMessage, ToolMessage
        from langchain_core.runnables import Runnable
        from langchain_core.tools import StructuredTool
        from langgraph.types import Command
    except ImportError:
        return

    if getattr(sm._build_task_tool, "_soothe_patched_config", False):
        return

    excluded_state_keys = sm._EXCLUDED_STATE_KEYS
    task_tool_description_template = sm.TASK_TOOL_DESCRIPTION

    def _build_task_tool(  # noqa: C901
        subagents: list[Any],
        task_description: str | None = None,
    ):
        subagent_graphs: dict[str, Runnable] = {
            spec["name"]: spec["runnable"] for spec in subagents
        }
        subagent_description_str = "\n".join(
            f"- {s['name']}: {s['description']}" for s in subagents
        )

        if task_description is None:
            description = task_tool_description_template.format(
                available_agents=subagent_description_str
            )
        elif "{available_agents}" in task_description:
            description = task_description.format(available_agents=subagent_description_str)
        else:
            description = task_description

        def _return_command_with_state_update(result: dict, tool_call_id: str) -> Any:
            if "messages" not in result:
                error_msg = (
                    "CompiledSubAgent must return a state containing a 'messages' key. "
                    "Custom StateGraphs used with CompiledSubAgent should include 'messages' "
                    "in their state schema to communicate results back to the main agent."
                )
                raise ValueError(error_msg)

            state_update = {k: v for k, v in result.items() if k not in excluded_state_keys}
            message_text = (
                result["messages"][-1].text.rstrip() if result["messages"][-1].text else ""
            )
            return Command(
                update={
                    **state_update,
                    "messages": [ToolMessage(message_text, tool_call_id=tool_call_id)],
                }
            )

        def _validate_and_prepare_state(
            subagent_type: str, description: str, runtime: ToolRuntime
        ) -> Any:
            # Debug logging to see actual subagent_type passed by LLM (IG-323)
            logger.debug(
                "[Task Tool] subagent_type='%s' description='%s' directive='%s'",
                subagent_type,
                description[:60],
                runtime.state.get("_subagent_routing_directive", "none"),
            )
            subagent = subagent_graphs[subagent_type]
            subagent_state = {
                k: v for k, v in runtime.state.items() if k not in excluded_state_keys
            }
            subagent_state["messages"] = [HumanMessage(content=description)]
            # IG-340: Propagate workspace from config.configurable to subagent
            # state. The executor passes workspace in config (not graph state),
            # so subagents like explore never see the thread workspace without
            # this explicit injection.
            configurable = (runtime.config or {}).get("configurable", {})
            cfg_workspace = configurable.get("workspace")
            if cfg_workspace and "workspace" not in subagent_state:
                subagent_state["workspace"] = cfg_workspace
            return subagent, subagent_state

        def task(
            description: Annotated[
                str,
                "A detailed description of the task for the subagent to perform autonomously. Include all necessary context and specify the expected output format.",  # noqa: E501
            ],
            subagent_type: Annotated[
                str,
                "The type of subagent to use. Must be one of the available agent types listed in the tool description.",
            ],
            runtime: ToolRuntime,
        ) -> Any:
            if subagent_type not in subagent_graphs:
                allowed_types = ", ".join([f"`{k}`" for k in subagent_graphs])
                return f"We cannot invoke subagent {subagent_type} because it does not exist, the only allowed types are {allowed_types}"
            if not runtime.tool_call_id:
                value_error_msg = "Tool call ID is required for subagent invocation"
                raise ValueError(value_error_msg)
            subagent, subagent_state = _validate_and_prepare_state(
                subagent_type, description, runtime
            )
            result = subagent.invoke(subagent_state, runtime.config)
            return _return_command_with_state_update(result, runtime.tool_call_id)

        async def atask(
            description: Annotated[
                str,
                "A detailed description of the task for the subagent to perform autonomously. Include all necessary context and specify the expected output format.",  # noqa: E501
            ],
            subagent_type: Annotated[
                str,
                "The type of subagent to use. Must be one of the available agent types listed in the tool description.",
            ],
            runtime: ToolRuntime,
        ) -> Any:
            if subagent_type not in subagent_graphs:
                allowed_types = ", ".join([f"`{k}`" for k in subagent_graphs])
                return f"We cannot invoke subagent {subagent_type} because it does not exist, the only allowed types are {allowed_types}"
            if not runtime.tool_call_id:
                value_error_msg = "Tool call ID is required for subagent invocation"
                raise ValueError(value_error_msg)
            subagent, subagent_state = _validate_and_prepare_state(
                subagent_type, description, runtime
            )
            result = await subagent.ainvoke(subagent_state, runtime.config)
            return _return_command_with_state_update(result, runtime.tool_call_id)

        built = StructuredTool.from_function(
            name="task",
            func=task,
            coroutine=atask,
            description=description,
        )
        return built

    _build_task_tool._soothe_patched_config = True  # type: ignore[attr-defined]
    sm._build_task_tool = _build_task_tool


# Apply patches at module import time
_patch_summarization_overwrite_handling()
_patch_summarization_token_count_optimization()
_patch_task_tool_propagates_parent_runnable_config()
