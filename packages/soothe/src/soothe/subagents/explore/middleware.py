"""LangChain ``create_agent`` middleware for the explore subagent."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import (
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command, Overwrite

from soothe.utils.subagent_emit import emit_subagent_wire_event

from .events import ExploreCompletedEvent, ExploreMilestoneEvent, ExploreStartedEvent
from .findings import extract_findings_from_tool_result, should_record_findings
from .prompts import EXPLORE_AGENT_SYSTEM, SYNTHESIZE
from .schemas import (
    ExploreAgentState,
    ExploreResult,
    ExploreSubagentConfig,
    format_explore_result_markdown,
)
from .search_target import resolve_explore_search_target

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Emit milestone logs when the planner proposes filesystem or execute tool calls.
_EXPLORE_MILESTONE_TOOL_NAMES = frozenset(
    {"glob", "grep", "ls", "read_file", "file_info", "execute"},
)


class ExploreWireMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Emit started wire event and persist resolved ``search_target``."""

    state_schema = ExploreAgentState

    def __init__(
        self,
        *,
        thoroughness: str,
        resolver_workspace: str,
    ) -> None:
        super().__init__()
        self._thoroughness = thoroughness
        self._resolver_workspace = resolver_workspace

    def before_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        explicit = state.get("search_target")
        search_target = resolve_explore_search_target(messages, explicit)
        updates: dict[str, Any] = {}
        if search_target and not (isinstance(explicit, str) and explicit.strip()):
            updates["search_target"] = search_target
        if state.get("explore_wire_started"):
            return updates or None
        logger.info("Explore: searching for '%s'", search_target[:80])
        emit_subagent_wire_event(
            ExploreStartedEvent(
                search_target=search_target,
                thoroughness=self._thoroughness,
            ).to_dict(),
            logger,
        )
        updates["explore_wire_started"] = True
        thread_ws = state.get("workspace") or self._resolver_workspace
        if thread_ws != self._resolver_workspace:
            logger.debug(
                "Explore: thread workspace '%s' overrides build-time default '%s' (IG-344)",
                thread_ws,
                self._resolver_workspace,
            )
        return updates

    async def abefore_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Delegate to sync hook so ``ainvoke`` / ``astream`` match ``invoke``."""
        return self.before_agent(state, runtime)


class ExploreFindingsMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Accumulate ``findings`` from readonly tool outputs via state reducer."""

    state_schema = ExploreAgentState

    def _merge_findings(
        self,
        request: ToolCallRequest,
        tm: ToolMessage | Command[Any],
    ) -> ToolMessage | Command[Any]:
        name = request.tool_call.get("name") if isinstance(request.tool_call, dict) else ""
        if isinstance(tm, ToolMessage):
            name = tm.name or name
        if not should_record_findings(str(name)):
            return tm
        if not isinstance(tm, ToolMessage):
            return tm
        rows = extract_findings_from_tool_result(request, tm)
        if not rows:
            return tm
        return Command(update={"messages": [tm], "findings": rows})

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        tm = handler(request)
        return self._merge_findings(request, tm)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tm = await handler(request)
        return self._merge_findings(request, tm)


class ExplorePromptBudgetMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Dynamic system prompt, iteration budget, wire milestones, forced synthesis."""

    state_schema = ExploreAgentState

    def __init__(
        self,
        model: BaseChatModel,
        explore_config: ExploreSubagentConfig,
        resolver_workspace: str,
        max_iterations: int,
        max_matches: int,
    ) -> None:
        super().__init__()
        self._model = model
        self._explore_config = explore_config
        self._resolver_workspace = resolver_workspace
        self._max_iterations = max_iterations
        self._max_matches = max_matches

    def after_model(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None
        last = messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return None
        names = {str(tc.get("name") or "") for tc in last.tool_calls}
        if not names & _EXPLORE_MILESTONE_TOOL_NAMES:
            return None
        planned_summary = _format_planned_tools(last.tool_calls)
        logger.info(
            "Explore: planned %d tools — %s",
            len(last.tool_calls),
            planned_summary,
        )
        emit_subagent_wire_event(
            ExploreMilestoneEvent(
                decision="continue",
                findings_count=len(state.get("findings") or []),
                iterations_used=state.get("explore_model_invocations", 0),
            ).to_dict(),
            logger,
        )
        return None

    async def aafter_model(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Delegate to sync hook so async agent runs emit milestone parity."""
        return self.after_model(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest[None],
        handler: Callable[[ModelRequest[None]], ModelResponse],
    ) -> ModelResponse | ExtendedModelResponse[ExploreResult]:
        state = request.state
        current = state.get("explore_model_invocations", 0)
        messages = request.messages
        thread_ws = state.get("workspace") or self._resolver_workspace
        search_target = resolve_explore_search_target(messages, state.get("search_target"))
        findings = state.get("findings") or []

        # IG-399: Truncate message history to keep only recent turns
        max_history = self._explore_config.max_history_messages_for_model
        if len(messages) > max_history:
            messages = messages[-max_history:]

        # IG-399: Truncate tool outputs in each message
        max_tool_chars = self._explore_config.max_tool_output_chars_per_turn
        truncated_messages = []
        for msg in messages:
            if isinstance(msg, ToolMessage):
                content = str(msg.content)
                if len(content) > max_tool_chars:
                    content = content[:max_tool_chars] + "...[truncated]"
                truncated_messages.append(
                    ToolMessage(content=content, tool_call_id=msg.tool_call_id)
                )
            else:
                truncated_messages.append(msg)
        messages = truncated_messages

        # IG-399: Early-stop detection when findings stall
        prev_findings_count = state.get("prev_findings_count", 0)
        new_findings_count = len(findings)
        stall_counter = state.get("findings_stall_counter", 0)

        if new_findings_count == prev_findings_count:
            stall_counter += 1
        else:
            stall_counter = 0

        # Force synthesis if findings have stalled for N consecutive turns
        early_stop_threshold = self._explore_config.early_stop_no_new_findings_turns
        if stall_counter >= early_stop_threshold and current > 0:
            logger.info(
                "Explore: early stop after %d turns with no new findings — synthesizing",
                stall_counter,
            )
            return self._synthesize_findings(findings, search_target, current)

        findings_so_far = ""
        if findings:
            findings_so_far = "\nFindings so far:\n" + "\n".join(
                f"- {f.get('path', 'unknown')}" for f in findings[:10]
            )

        if current >= self._max_iterations:
            logger.info(
                "Explore: budget exhausted after %d model turns — synthesizing result",
                current,
            )
            return self._synthesize_findings(findings, search_target, current)

        body = EXPLORE_AGENT_SYSTEM.format(
            search_target=search_target,
            workspace=thread_ws,
            thoroughness=self._explore_config.thoroughness,
            max_iterations=self._max_iterations,
            max_read_lines=self._explore_config.max_read_lines,
            findings_so_far=findings_so_far,
        )
        req = request.override(messages=messages, system_message=SystemMessage(content=body))
        response = handler(req)
        return ExtendedModelResponse(
            model_response=response,
            command=Command(
                update={
                    "explore_model_invocations": current + 1,
                    "prev_findings_count": new_findings_count,
                    "findings_stall_counter": stall_counter,
                }
            ),
        )

    def _synthesize_findings(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
        current_iter: int,
    ) -> ExtendedModelResponse[ExploreResult]:
        """Synthesize findings into structured result (IG-399)."""
        detail_lines = [
            f"- {f.get('path', 'unknown')}: {(f.get('snippet') or '')[:100] or '(no snippet)'}"
            for f in findings[:20]
        ]
        findings_detail = "\n".join(detail_lines) if detail_lines else "No findings"
        prompt = SYNTHESIZE.format(
            search_target=search_target,
            findings_detail=findings_detail,
            max_matches=self._max_matches,
        )
        structured = self._model.with_structured_output(ExploreResult).invoke(
            [HumanMessage(content=prompt)]
        )
        logger.info(
            "Explore: synthesized result after %d iterations",
            current_iter,
        )
        return ExtendedModelResponse(
            model_response=ModelResponse(
                result=[AIMessage(content="Synthesized summary (early stop or budget exhausted).")],
                structured_response=structured,
            ),
            command=Command(
                update={
                    "explore_model_invocations": current_iter + 1,
                    "prev_findings_count": len(findings),
                    "findings_stall_counter": 0,
                }
            ),
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[None],
        handler: Callable[
            [ModelRequest[None]],
            Awaitable[ModelResponse],
        ],
    ) -> ModelResponse | ExtendedModelResponse[ExploreResult]:
        state = request.state
        current = state.get("explore_model_invocations", 0)
        messages = request.messages
        thread_ws = state.get("workspace") or self._resolver_workspace
        search_target = resolve_explore_search_target(messages, state.get("search_target"))
        findings = state.get("findings") or []
        findings_so_far = ""
        if findings:
            findings_so_far = "\nFindings so far:\n" + "\n".join(
                f"- {f.get('path', 'unknown')}" for f in findings[:10]
            )

        if current >= self._max_iterations:
            detail_lines = [
                f"- {f.get('path', 'unknown')}: {(f.get('snippet') or '')[:100] or '(no snippet)'}"
                for f in findings[:20]
            ]
            findings_detail = "\n".join(detail_lines) if detail_lines else "No findings"
            prompt = SYNTHESIZE.format(
                search_target=search_target,
                findings_detail=findings_detail,
                max_matches=self._max_matches,
            )
            structured = await self._model.with_structured_output(ExploreResult).ainvoke(
                [HumanMessage(content=prompt)]
            )
            logger.info(
                "Explore: budget exhausted after %d model turns — synthesized result",
                current,
            )
            return ExtendedModelResponse(
                model_response=ModelResponse(
                    result=[
                        AIMessage(
                            content="Iteration budget reached; returning synthesized summary."
                        )
                    ],
                    structured_response=structured,
                ),
                command=Command(
                    update={"explore_model_invocations": current + 1},
                ),
            )

        body = EXPLORE_AGENT_SYSTEM.format(
            search_target=search_target,
            workspace=thread_ws,
            thoroughness=self._explore_config.thoroughness,
            max_iterations=self._max_iterations,
            max_read_lines=self._explore_config.max_read_lines,
            findings_so_far=findings_so_far,
        )
        req = request.override(system_message=SystemMessage(content=body))
        response = await handler(req)
        return ExtendedModelResponse(
            model_response=response,
            command=Command(update={"explore_model_invocations": current + 1}),
        )


class ExploreFinalizeMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Emit completion wire event and collapse messages to markdown delegate final."""

    state_schema = ExploreAgentState

    def __init__(
        self,
        *,
        thoroughness: str,
    ) -> None:
        super().__init__()
        self._thoroughness = thoroughness

    def after_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        structured = state.get("structured_response")
        if structured is None:
            return None
        result = (
            structured
            if isinstance(structured, ExploreResult)
            else ExploreResult.model_validate(structured)
        )
        messages = state.get("messages") or []
        search_target = resolve_explore_search_target(
            messages,
            state.get("search_target"),
        )
        findings = state.get("findings") or []
        iterations_used = state.get("explore_model_invocations", 0)
        start_time = time.perf_counter()
        md = format_explore_result_markdown(result)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        emit_subagent_wire_event(
            ExploreCompletedEvent(
                total_findings=len(findings),
                thoroughness=self._thoroughness,
                iterations_used=iterations_used,
                duration_ms=elapsed_ms,
                search_target=search_target,
            ).to_dict(),
            logger,
        )
        logger.info("Explore: completed %d matches in %dms", len(result.matches), elapsed_ms)
        return {"messages": Overwrite([AIMessage(content=md)])}

    async def aafter_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Delegate to sync hook so ``ainvoke`` collapses delegate markdown like ``invoke``."""
        return self.after_agent(state, runtime)


def _format_planned_tools(tool_calls: list[Any]) -> str:
    snippets: list[str] = []
    for i, tc in enumerate(tool_calls, start=1):
        if isinstance(tc, dict):
            name = str(tc.get("name") or "?")
            args = tc.get("args")
        else:
            name = str(getattr(tc, "name", None) or "?")
            args = getattr(tc, "args", None)
        arg_str = _summarize_tool_args(args)
        snippets.append(f"{i}.{name}({arg_str})" if arg_str else f"{i}.{name}")
    return " | ".join(snippets)


def _summarize_tool_args(
    args: Any,
    *,
    value_max: int = 160,
    total_max: int = 480,
) -> str:
    if args is None:
        return ""
    if isinstance(args, str):
        s = args.strip()
        return (s[: value_max - 3] + "...") if len(s) > value_max else s
    if not isinstance(args, dict):
        s = str(args)
        return (s[: total_max - 3] + "...") if len(s) > total_max else s
    parts: list[str] = []
    for key in sorted(args.keys()):
        val = args[key]
        vs = val if isinstance(val, str) else repr(val)
        if len(vs) > value_max:
            vs = vs[: value_max - 3] + "..."
        parts.append(f"{key}={vs}")
    out = ", ".join(parts)
    if len(out) > total_max:
        return out[: total_max - 3] + "..."
    return out


def build_explore_middleware_stack(
    model: BaseChatModel,
    explore_config: ExploreSubagentConfig,
    resolver_workspace: str,
    *,
    max_iterations: int,
    max_matches: int,
) -> list[AgentMiddleware[Any, None]]:
    """Ordered middleware list for ``create_agent`` (outermost first)."""
    return [
        ExploreWireMiddleware(
            thoroughness=explore_config.thoroughness,
            resolver_workspace=resolver_workspace,
        ),
        ExploreFindingsMiddleware(),
        ExplorePromptBudgetMiddleware(
            model=model,
            explore_config=explore_config,
            resolver_workspace=resolver_workspace,
            max_iterations=max_iterations,
            max_matches=max_matches,
        ),
        ExploreFinalizeMiddleware(
            thoroughness=explore_config.thoroughness,
        ),
    ]
