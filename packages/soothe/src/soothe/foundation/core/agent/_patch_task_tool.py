"""Runtime patch for deepagents task tool config propagation.

This patch ensures parent runnable config is propagated to subagent invocations,
enabling proper stream event forwarding in nested graph execution.

Note: Do not enable PEP 563 (``from __future__ import annotations``) in this module
when adding patches that use ``inspect.signature`` for runtime type checking.
The ``runtime`` parameter must stay annotated as ``ToolRuntime`` (not ``Any``) so
LangGraph's tool node injects it; see ``_get_all_injected_args`` in tool_node.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Annotated, Any

logger = logging.getLogger(__name__)

# Used in patched ``task`` / ``atask`` signatures so LangGraph detects injection.
try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at lint import time
    ToolRuntime = Any  # type: ignore[misc,assignment]


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
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from langchain_core.runnables import Runnable
        from langchain_core.tools import StructuredTool
        from langgraph.types import Command
    except ImportError:
        return

    if getattr(sm._build_task_tool, "_soothe_patched_config", False):
        return

    excluded_state_keys = sm._EXCLUDED_STATE_KEYS
    task_tool_description_template = sm.TASK_TOOL_DESCRIPTION
    # Import create_sub_agent for compiling raw SubAgent specs
    create_sub_agent = sm.create_sub_agent

    def _build_task_tool(  # noqa: C901
        subagents: list[Any],
        task_description: str | None = None,
        *,
        private_state_keys: frozenset[str] = frozenset(),
        state_schema: Any = None,
    ):
        # Combine excluded_state_keys (deepagents default) with private_state_keys
        all_excluded_keys = excluded_state_keys | private_state_keys

        # Compile raw SubAgent specs first (deepagents 0.6.10+ API)
        # Raw specs lack 'runnable'; they need create_sub_agent() compilation.
        def _compile_spec(spec: Any) -> Any:
            if "runnable" in spec:
                # CompiledSubAgent: apply config metadata
                runnable = spec["runnable"].with_config(
                    {
                        "metadata": {"lc_agent_name": spec["name"]},
                        "run_name": spec["name"],
                    }
                )
                return {
                    "name": spec["name"],
                    "description": spec["description"],
                    "runnable": runnable,
                }
            # Raw SubAgent: compile via create_sub_agent
            return {
                "name": spec["name"],
                "description": spec["description"],
                "runnable": create_sub_agent(spec, state_schema=state_schema),
            }

        compiled_subagents = [_compile_spec(spec) for spec in subagents]
        subagent_graphs: dict[str, Runnable] = {
            spec["name"]: spec["runnable"] for spec in compiled_subagents
        }
        subagent_description_str = "\n".join(
            f"- {s['name']}: {s['description']}" for s in compiled_subagents
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

            state_update = {k: v for k, v in result.items() if k not in all_excluded_keys}

            # Handle structured_response serialization (deepagents 0.6.10+)
            structured = result.get("structured_response")
            if structured is not None:
                if hasattr(structured, "model_dump_json"):
                    content: str = structured.model_dump_json()
                elif dataclasses.is_dataclass(structured) and not isinstance(structured, type):
                    content = json.dumps(dataclasses.asdict(structured))
                else:
                    content = json.dumps(structured)
            else:
                # Walk back to find last AIMessage with non-empty text
                # (handles Anthropic trailing empty AIMessage)
                content = ""
                for msg in reversed(result["messages"]):
                    if isinstance(msg, AIMessage):
                        text = msg.text.rstrip() if msg.text else ""
                        if text:
                            content = text
                            break

            return Command(
                update={
                    **state_update,
                    "messages": [ToolMessage(content, tool_call_id=tool_call_id)],
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
            subagent_state = {k: v for k, v in runtime.state.items() if k not in all_excluded_keys}
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


def apply_task_tool_patch() -> None:
    """Apply task tool config propagation patch."""
    _patch_task_tool_propagates_parent_runnable_config()


__all__ = [
    "apply_task_tool_patch",
    "_patch_task_tool_propagates_parent_runnable_config",
]
