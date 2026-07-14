"""Runtime patch for soothe_deepagents task tool config propagation.

This patch ensures parent runnable config is propagated to subagent invocations,
enabling proper stream event forwarding in nested graph execution.

When ``agent.runtime.general_purpose_subagent`` is false (default), the soothe_deepagents
``general-purpose`` delegate is removed from the task tool listing and blocked at
invoke time.

Note: Do not enable PEP 563 (``from __future__ import annotations``) in this module
when adding patches that use ``inspect.signature`` for runtime type checking.
The ``runtime`` parameter must stay annotated as ``ToolRuntime`` (not ``Any``) so
LangGraph's tool node injects it; see ``_get_all_injected_args`` in tool_node.
"""

from __future__ import annotations

import contextlib
import contextvars
import dataclasses
import json
import logging
from collections.abc import Iterator
from typing import Annotated, Any

logger = logging.getLogger(__name__)

GENERAL_PURPOSE_SUBAGENT_NAME = "general-purpose"
_GP_TASK_DESC_SECTION_START = "7. When only the general-purpose agent"
_GP_TASK_DESC_SECTION_END = "### Example usage with custom agents:"

# Used in patched ``task`` / ``atask`` signatures so LangGraph detects injection.
try:
    from langchain.tools import ToolRuntime
except ImportError:  # pragma: no cover - optional at lint import time
    ToolRuntime = Any  # type: ignore[misc,assignment]

_general_purpose_subagent_enabled: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "soothe_general_purpose_subagent_enabled",
    default=False,
)


def general_purpose_subagent_enabled() -> bool:
    """Return whether soothe_deepagents general-purpose subagent is active for this build."""
    return _general_purpose_subagent_enabled.get()


@contextlib.contextmanager
def general_purpose_subagent_build_context(enabled: bool) -> Iterator[None]:
    """Scope ``create_deep_agent`` so task-tool patches honor runtime config."""
    token = _general_purpose_subagent_enabled.set(enabled)
    try:
        yield
    finally:
        _general_purpose_subagent_enabled.reset(token)


def _filter_general_purpose_subagents(subagents: list[Any]) -> list[Any]:
    return [spec for spec in subagents if spec.get("name") != GENERAL_PURPOSE_SUBAGENT_NAME]


def _task_tool_description_template(base_template: str, *, include_general_purpose: bool) -> str:
    if include_general_purpose:
        return base_template
    start = base_template.find(_GP_TASK_DESC_SECTION_START)
    end = base_template.find(_GP_TASK_DESC_SECTION_END)
    if start == -1 or end == -1 or end <= start:
        return base_template
    return base_template[:start].rstrip() + "\n\n" + base_template[end:]


def _patch_subagent_middleware_filters_general_purpose() -> None:
    try:
        from soothe_deepagents.middleware import subagents as sm
    except ImportError:
        return

    if getattr(sm.SubAgentMiddleware.__init__, "_soothe_gp_filter_patched", False):
        return

    original_init = sm.SubAgentMiddleware.__init__

    def _patched_init(self, *args: Any, **kwargs: Any) -> None:
        if not general_purpose_subagent_enabled():
            subagents = kwargs.get("subagents")
            if subagents is not None:
                kwargs["subagents"] = _filter_general_purpose_subagents(list(subagents))
        original_init(self, *args, **kwargs)

    _patched_init._soothe_gp_filter_patched = True  # type: ignore[attr-defined]
    sm.SubAgentMiddleware.__init__ = _patched_init  # type: ignore[method-assign]


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
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        from langchain_core.runnables import Runnable
        from langchain_core.tools import StructuredTool
        from langgraph.types import Command
        from soothe_deepagents.middleware import subagents as sm
    except ImportError:
        return

    if getattr(sm._build_task_tool, "_soothe_patched_config", False):
        return

    excluded_state_keys = sm._EXCLUDED_STATE_KEYS
    # Parent-owned channels: parallel subagent completions must not merge these back
    # (LangGraph LastValue rejects multiple ``workspace`` writes per step).
    parent_owned_state_keys = frozenset({"workspace"})
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
        include_general_purpose = general_purpose_subagent_enabled()
        if not include_general_purpose:
            subagents = _filter_general_purpose_subagents(subagents)

        # Combine excluded_state_keys (soothe_deepagents default) with private_state_keys
        all_excluded_keys = excluded_state_keys | private_state_keys | parent_owned_state_keys

        # Compile raw SubAgent specs first (soothe_deepagents 0.6.10+ API)
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

        description_template = _task_tool_description_template(
            task_tool_description_template,
            include_general_purpose=include_general_purpose,
        )
        if task_description is None:
            description = description_template.format(available_agents=subagent_description_str)
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

            # Handle structured_response serialization (soothe_deepagents 0.6.10+)
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
            # so subagents never see the thread workspace without
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
    _patch_subagent_middleware_filters_general_purpose()


__all__ = [
    "GENERAL_PURPOSE_SUBAGENT_NAME",
    "apply_task_tool_patch",
    "general_purpose_subagent_build_context",
    "general_purpose_subagent_enabled",
    "_patch_task_tool_propagates_parent_runnable_config",
]
