"""Deepagents compatibility patches.

Patches are applied at import time and isolated from CoreAgent logic.
These patches fix upstream issues in deepagents that affect Soothe's execution.

Note: Do not enable PEP 563 (``from __future__ import annotations``) in this module.
``StructuredTool._injected_args_keys`` uses ``inspect.signature`` and
``_is_injected_arg_type(parameter.annotation)``. String annotations would prevent
``ToolRuntime`` from being recognized, so ``runtime`` would be stripped during
Pydantic validation and the task tool would fail at runtime.
"""

import logging
from typing import Annotated, Any

logger = logging.getLogger(__name__)

# Used in patched ``task`` / ``atask`` signatures so LangGraph detects injection.
try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at lint import time
    ToolRuntime = Any  # type: ignore[misc,assignment]


def _patch_summarization_overwrite_handling() -> None:
    """Patch deepagents SummarizationMiddleware for Overwrite wrapper handling.

    deepagents' SummarizationMiddleware._apply_event_to_messages does not
    handle langgraph's Overwrite wrapper that PatchToolCallsMiddleware may
    leave in request.messages. This patch unwraps it so ``list(messages)`` succeeds.

    This is a temporary workaround until fixed upstream in deepagents.
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


def _patch_task_tool_propagates_parent_runnable_config() -> None:
    """Propagate parent ``ToolRuntime.config`` into subagent ``invoke`` / ``ainvoke``.

    Upstream ``deepagents`` ``task`` tool calls ``subagent.ainvoke(subagent_state)``
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
                description[:100],
                runtime.state.get("_subagent_routing_directive", "none"),
            )
            subagent = subagent_graphs[subagent_type]
            subagent_state = {
                k: v for k, v in runtime.state.items() if k not in excluded_state_keys
            }
            subagent_state["messages"] = [HumanMessage(content=description)]
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
_patch_task_tool_propagates_parent_runnable_config()
