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

from .events import ExploreCompletedEvent, ExploreStartedEvent
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
            logger.debug("[ExploreFindings] skip recording for tool=%s", name)
            return tm
        if not isinstance(tm, ToolMessage):
            logger.debug(
                "[ExploreFindings] result is Command, not ToolMessage: tool=%s type=%s",
                name,
                type(tm).__name__,
            )
            return tm
        rows = extract_findings_from_tool_result(request, tm)
        if not rows:
            logger.debug("[ExploreFindings] no rows extracted from tool=%s", name)
            return tm
        logger.debug(
            "[ExploreFindings] returning Command with findings: tool=%s rows=%d",
            name,
            len(rows),
        )
        return Command(update={"messages": [tm], "findings": rows})

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name") if isinstance(request.tool_call, dict) else "?"
        logger.debug("[ExploreFindings] wrap_tool_call START: tool=%s", tool_name)
        try:
            tm = handler(request)
            logger.debug(
                "[ExploreFindings] wrap_tool_call END: tool=%s result_type=%s",
                tool_name,
                type(tm).__name__,
            )
            merged = self._merge_findings(request, tm)
            logger.debug(
                "[ExploreFindings] merge_findings DONE: tool=%s merged_type=%s",
                tool_name,
                type(merged).__name__,
            )
            return merged
        except Exception as e:
            logger.error(
                "[ExploreFindings] wrap_tool_call ERROR: tool=%s error=%s",
                tool_name,
                e,
                exc_info=True,
            )
            raise

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name") if isinstance(request.tool_call, dict) else "?"
        logger.debug("[ExploreFindings] awrap_tool_call START: tool=%s", tool_name)
        try:
            tm = await handler(request)
            logger.debug(
                "[ExploreFindings] awrap_tool_call END: tool=%s result_type=%s",
                tool_name,
                type(tm).__name__,
            )
            merged = self._merge_findings(request, tm)
            logger.debug(
                "[ExploreFindings] merge_findings DONE: tool=%s merged_type=%s",
                tool_name,
                type(merged).__name__,
            )
            return merged
        except Exception as e:
            logger.error(
                "[ExploreFindings] awrap_tool_call ERROR: tool=%s error=%s",
                tool_name,
                e,
                exc_info=True,
            )
            raise


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
        synthesis_model: BaseChatModel | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._explore_config = explore_config
        self._resolver_workspace = resolver_workspace
        self._max_iterations = max_iterations
        self._max_matches = max_matches
        # Use separate fast model for synthesis if provided
        self._synthesis_model = synthesis_model or model

    def after_model(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        # REMOVED: Milestone event logging (per user request)
        # This middleware no longer emits subagent.explore.milestone events
        return None

    async def aafter_model(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Delegate to sync hook (no milestone events)."""
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
        """Synthesize findings into structured result (IG-399).

        Performance optimization (May 2026):
        - Uses fast model for synthesis (3x faster than default model)
        - Limits findings payload to 15 entries (reduced from 20)
        - Truncates snippets to 100 chars (same as before)
        - Logs synthesis timing for performance monitoring
        """
        start_time = time.perf_counter()
        logger.info(
            "Explore: starting synthesis with %d findings (iter=%d)",
            len(findings),
            current_iter,
        )

        # Reduce payload size for faster synthesis (15 findings × 100 chars)
        detail_lines = [
            f"- {f.get('path', 'unknown')}: {(f.get('snippet') or '')[:100] or '(no snippet)'}"
            for f in findings[:15]  # Changed from 20 to 15
        ]
        findings_detail = "\n".join(detail_lines) if detail_lines else "No findings"
        prompt = SYNTHESIZE.format(
            search_target=search_target,
            findings_detail=findings_detail,
            max_matches=self._max_matches,
        )

        logger.debug(
            "Explore: synthesis prompt size: %d chars (%d findings)",
            len(prompt),
            len(detail_lines),
        )

        # Use fast model for structured output (optimization)
        structured = self._synthesis_model.with_structured_output(ExploreResult).invoke(
            [HumanMessage(content=prompt)]
        )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Explore: synthesis completed in %.1fs (%d findings → %d matches)",
            elapsed,
            len(findings),
            len(structured.matches),
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
            start_time = time.perf_counter()
            logger.info(
                "Explore: starting synthesis with %d findings (iter=%d, budget exhausted)",
                len(findings),
                current,
            )

            # Reduce payload size for faster synthesis (15 findings × 100 chars)
            detail_lines = [
                f"- {f.get('path', 'unknown')}: {(f.get('snippet') or '')[:100] or '(no snippet)'}"
                for f in findings[:15]  # Changed from 20 to 15
            ]
            findings_detail = "\n".join(detail_lines) if detail_lines else "No findings"
            prompt = SYNTHESIZE.format(
                search_target=search_target,
                findings_detail=findings_detail,
                max_matches=self._max_matches,
            )

            logger.debug(
                "Explore: synthesis prompt size: %d chars (%d findings)",
                len(prompt),
                len(detail_lines),
            )

            # Use fast model for structured output (optimization)
            structured = await self._synthesis_model.with_structured_output(ExploreResult).ainvoke(
                [HumanMessage(content=prompt)]
            )

            elapsed = time.perf_counter() - start_time
            logger.info(
                "Explore: synthesis completed in %.1fs (%d findings → %d matches)",
                elapsed,
                len(findings),
                len(structured.matches),
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


def build_explore_middleware_stack(
    model: BaseChatModel,
    explore_config: ExploreSubagentConfig,
    resolver_workspace: str,
    *,
    max_iterations: int,
    max_matches: int,
    synthesis_model: BaseChatModel | None = None,
) -> list[AgentMiddleware[Any, None]]:
    """Ordered middleware list for ``create_agent`` (outermost first).

    Args:
        model: Primary model for exploration planning.
        explore_config: Explore-specific configuration.
        resolver_workspace: Resolver-provided workspace default.
        max_iterations: Maximum model turns before synthesis.
        max_matches: Maximum matches to return in result.
        synthesis_model: Optional fast model for synthesis (defaults to model).

    Returns:
        Middleware stack with budget, findings, wire, and finalize middlewares.
    """
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
            synthesis_model=synthesis_model,
        ),
        ExploreFinalizeMiddleware(
            thoroughness=explore_config.thoroughness,
        ),
    ]
