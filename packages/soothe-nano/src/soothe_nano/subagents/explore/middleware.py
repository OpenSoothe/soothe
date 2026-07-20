"""LangChain ``create_agent`` middleware for the explore subagent."""

from __future__ import annotations

import asyncio
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

from soothe_nano.config.middleware_access import agent_middleware_config
from soothe_nano.utils.llm.structured import (
    StructuredOutputError,
    invoke_structured_chat_typed,
)
from soothe_nano.utils.subagent_emit import emit_subagent_wire_event

from .events import ExploreCompletedEvent, ExploreStartedEvent, ExploreStepCompletedEvent
from .findings import extract_findings_from_tool_result, should_record_findings
from .normalize import coerce_explore_result_dict
from .partial import build_explore_result_from_findings
from .prompts import SYNTHESIZE, format_explore_agent_system
from .schemas import (
    ExploreAgentState,
    ExploreResult,
    ExploreSubagentConfig,
    format_explore_result_markdown,
)
from .search_target import resolve_explore_search_target

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)

_SYNTHESIS_FINDING_SNIPPET_CHARS = 160


def _keyword_overlap_score(finding: dict[str, Any], query: str) -> float:
    """Simple lexical relevance fallback for ranking findings.

    Uses token overlap between query words and ``path`` + ``snippet`` content.
    """
    query_tokens = {t for t in str(query).lower().split() if t}
    if not query_tokens:
        return 0.0
    haystack = f"{finding.get('path', '')} {finding.get('snippet', '')}".lower()
    if not haystack.strip():
        return 0.0
    score = 0.0
    for token in query_tokens:
        if token in haystack:
            score += 1.0
    return score / float(len(query_tokens))


def _rank_findings_by_keyword_overlap(
    findings: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Return findings sorted by lightweight lexical relevance."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for finding in findings:
        score = _keyword_overlap_score(finding, query)
        finding["relevance"] = "high" if score >= 0.66 else ("medium" if score >= 0.33 else "low")
        scored.append((score, finding))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored]


def _thread_workspace_from_agent_runtime(runtime: Any) -> str | None:
    """Resolve client thread workspace for explore graph state (IG-328).

    ``before_agent`` receives LangGraph ``Runtime`` (or compatible). Prefer
    ``runtime.config["configurable"]["workspace"]`` from the parent invoke, then
    ``langgraph.config.get_config()`` when available.

    Args:
        runtime: Agent ``Runtime`` from middleware (may be None in tests).

    Returns:
        Stripped workspace path, or ``None``.
    """
    if runtime is not None:
        cfg = getattr(runtime, "config", None)
        if isinstance(cfg, dict):
            conf = cfg.get("configurable") or {}
            if isinstance(conf, dict):
                w = conf.get("workspace")
                if isinstance(w, str) and w.strip():
                    return w.strip()
    try:
        from langgraph.config import get_config

        c = get_config()
        if isinstance(c, dict):
            conf = c.get("configurable") or {}
            if isinstance(conf, dict):
                w = conf.get("workspace")
                if isinstance(w, str) and w.strip():
                    return w.strip()
    except Exception:  # noqa: S110
        pass
    return None


class ExploreWireMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Emit explore wire events, resolve ``search_target``, and seed ``workspace`` on state (IG-328)."""

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
        # Persist thread workspace on graph state so ``ToolRuntime.state`` exposes it to
        # Thread workspace for filesystem tools (IG-328).
        if not str(state.get("workspace") or "").strip():
            tw = _thread_workspace_from_agent_runtime(runtime)
            if tw:
                updates["workspace"] = tw
            elif self._resolver_workspace.strip():
                updates["workspace"] = self._resolver_workspace.strip()
        if search_target and not (isinstance(explicit, str) and explicit.strip()):
            updates["search_target"] = search_target
        if state.get("explore_wire_started"):
            return updates or None
        logger.info("Explore: searching for '%s'", search_target)
        emit_subagent_wire_event(
            ExploreStartedEvent(
                search_target=search_target,
                thoroughness=self._thoroughness,
            ).to_dict(),
            logger,
        )
        updates["explore_wire_started"] = True
        updates["explore_started_at_monotonic"] = time.perf_counter()
        return updates

    async def abefore_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        """Delegate to sync hook so ``ainvoke`` / ``astream`` match ``invoke``."""
        return self.before_agent(state, runtime)


class ExploreFindingsMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Accumulate ``findings`` from readonly tool outputs via state reducer.

    Also emits step-completed wire events for TUI display.
    """

    state_schema = ExploreAgentState

    @staticmethod
    def _finding_fingerprint(row: dict[str, Any]) -> tuple[str, str]:
        path = str(row.get("path", "") or "").strip()
        snippet = str(row.get("snippet", "") or "").strip()
        return path, snippet

    def _emit_step_event(
        self,
        request: ToolCallRequest,
        tm: ToolMessage | Command[Any],
    ) -> None:
        """Emit ExploreStepCompletedEvent for TUI progress display."""
        tool_name = ""
        args_preview = ""
        result_preview = ""

        if isinstance(request.tool_call, dict):
            tool_name = str(request.tool_call.get("name", ""))
            args_raw = request.tool_call.get("args", {})
            if isinstance(args_raw, dict):
                args_preview = str(args_raw)[:120]
            elif isinstance(args_raw, str):
                args_preview = args_raw[:120]

        if isinstance(tm, ToolMessage):
            tool_name = tm.name or tool_name
            content = tm.content
            if isinstance(content, str):
                result_preview = content[:120]
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                result_preview = "".join(parts)[:120]

        if tool_name:
            emit_subagent_wire_event(
                ExploreStepCompletedEvent(
                    tool_name=tool_name,
                    args_preview=args_preview,
                    result_preview=result_preview,
                ).to_dict(),
                logger,
            )

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
        state_findings = request.state.get("findings") if isinstance(request.state, dict) else None
        existing = state_findings if isinstance(state_findings, list) else []
        existing_keys = {
            self._finding_fingerprint(row) for row in existing if isinstance(row, dict)
        }
        novel_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = self._finding_fingerprint(row)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            novel_rows.append(row)
        if not novel_rows:
            return tm
        return Command(update={"messages": [tm], "findings": novel_rows})

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        try:
            result = handler(request)
            self._emit_step_event(request, result)
            return self._merge_findings(request, result)
        except Exception as e:
            tool_name = (
                request.tool_call.get("name") if isinstance(request.tool_call, dict) else "?"
            )
            logger.error("[ExploreFindings] tool=%s error=%s", tool_name, e, exc_info=True)
            raise

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            result = await handler(request)
            self._emit_step_event(request, result)
            return self._merge_findings(request, result)
        except Exception as e:
            tool_name = (
                request.tool_call.get("name") if isinstance(request.tool_call, dict) else "?"
            )
            logger.error("[ExploreFindings] tool=%s error=%s", tool_name, e, exc_info=True)
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
        soothe_config: SootheConfig | None = None,
    ) -> None:
        super().__init__()
        self._model = model
        self._explore_config = explore_config
        self._resolver_workspace = resolver_workspace
        self._max_iterations = max_iterations
        self._max_matches = max_matches
        # Use separate fast model for synthesis if provided
        self._synthesis_model = synthesis_model or model
        self._soothe_config = soothe_config

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

    def _prepare_model_turn_state(
        self,
        state: ExploreAgentState,
        messages: list[Any],
    ) -> tuple[list[Any], int, list[dict[str, Any]], int, int]:
        """Apply history/tool-output truncation and compute finding-stall counters."""
        current = state.get("explore_model_invocations", 0)
        findings = state.get("findings") or []

        max_history = self._explore_config.max_history_messages_for_model
        if len(messages) > max_history:
            messages = messages[-max_history:]

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

        prev_findings_count = state.get("prev_findings_count", 0)
        new_findings_count = len(findings)
        stall_counter = state.get("findings_stall_counter", 0)
        if new_findings_count == prev_findings_count:
            stall_counter += 1
        else:
            stall_counter = 0
        return messages, current, findings, new_findings_count, stall_counter

    def wrap_model_call(
        self,
        request: ModelRequest[None],
        handler: Callable[[ModelRequest[None]], ModelResponse],
    ) -> ModelResponse | ExtendedModelResponse[ExploreResult]:
        state = request.state
        messages = request.messages
        thread_ws = state.get("workspace") or self._resolver_workspace
        search_target = resolve_explore_search_target(messages, state.get("search_target"))
        messages, current, findings, new_findings_count, stall_counter = (
            self._prepare_model_turn_state(state, messages)
        )

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

        body = format_explore_agent_system(
            search_target=search_target,
            workspace=thread_ws,
            thoroughness=self._explore_config.thoroughness,
            max_iterations=self._max_iterations,
            max_read_lines=self._explore_config.max_read_lines,
            findings_so_far=findings_so_far,
        )
        req = request.override(messages=messages, system_message=SystemMessage(content=body))
        try:
            response = handler(req)
        except Exception as exc:
            if not findings:
                logger.error(
                    "Explore: model turn failed with no findings (%s)",
                    exc,
                    exc_info=True,
                )
                raise
            logger.warning(
                "Explore: model turn failed (%s); returning partial results from %d findings",
                exc,
                len(findings),
            )
            return self._synthesize_findings(
                findings,
                search_target,
                current,
                failure_reason=str(exc),
            )
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

    def _rank_findings_for_synthesis(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
    ) -> list[dict[str, Any]]:
        """Apply lightweight relevance ranking before synthesis (sync)."""
        if not findings:
            return findings
        try:
            return _rank_findings_by_keyword_overlap(findings, search_target)
        except Exception as exc:
            logger.warning(
                "Explore: finding ranking failed (%s); using findings in original order",
                exc,
            )
            return findings

    async def _arank_findings_for_synthesis(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
    ) -> list[dict[str, Any]]:
        """Apply lightweight relevance ranking before synthesis (async)."""
        if not findings:
            return findings
        try:
            return _rank_findings_by_keyword_overlap(findings, search_target)
        except Exception as exc:
            logger.warning(
                "Explore: finding ranking failed (%s); using findings in original order",
                exc,
            )
        return findings

    def _build_synthesis_prompt(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
    ) -> tuple[str, int]:
        max_findings = self._explore_config.max_findings_for_synthesis
        detail_lines = [
            f"- {f.get('path', 'unknown')}: "
            f"{(f.get('snippet') or '')[:_SYNTHESIS_FINDING_SNIPPET_CHARS] or '(no snippet)'}"
            for f in findings[:max_findings]
        ]
        findings_detail = "\n".join(detail_lines) if detail_lines else "No findings"
        prompt = SYNTHESIZE.format(
            search_target=search_target,
            findings_detail=findings_detail,
            max_matches=self._max_matches,
        )
        logger.debug(
            "Explore: synthesis prompt size: %d chars (%d findings, max=%d)",
            len(prompt),
            len(detail_lines),
            max_findings,
        )
        return prompt, len(detail_lines)

    @staticmethod
    def _same_model_instance(left: Any, right: Any) -> bool:
        """Best-effort check for model identity without requiring hashability."""
        if left is right:
            return True
        if left is None or right is None:
            return False
        return repr(left) == repr(right)

    @staticmethod
    def _synthesis_repair_message() -> HumanMessage:
        """Compact repair hint appended on structured-output retry attempts."""
        return HumanMessage(
            content=(
                "Structured output repair: return valid ExploreResult JSON with required keys "
                "target, matches, summary. If no matches exist, return matches: []."
            )
        )

    def _normalize_synthesis_payload(
        self,
        data: dict[str, Any],
        *,
        search_target: str,
    ) -> dict[str, Any]:
        """Coerce provider payload into a strict ExploreResult-compatible dict."""
        return coerce_explore_result_dict(
            data,
            search_target=search_target,
            thoroughness=self._explore_config.thoroughness,
            max_matches=self._max_matches,
        )

    def _invoke_synthesis_llm_sync(self, prompt: str, *, search_target: str) -> ExploreResult:
        from soothe_nano.utils.llm.invoke_policy import (
            llm_rate_limit_config_from,
            run_with_llm_call_policy_sync,
        )

        timeout = self._explore_config.synthesis_timeout_seconds
        llm_config = llm_rate_limit_config_from(self._soothe_config).model_copy(
            update={
                "call_timeout_seconds": max(int(timeout), 30),
                "call_timeout_max_seconds": max(int(timeout), 30),
            }
        )

        retries = max(0, int(self._explore_config.synthesis_validation_retries))
        models: list[tuple[str, BaseChatModel]] = [("synthesis", self._synthesis_model)]
        if (
            self._explore_config.synthesis_fallback_to_primary_model
            and not self._same_model_instance(self._synthesis_model, self._model)
        ):
            models.append(("primary", self._model))

        last_exc: Exception | None = None
        for model_name, model in models:
            for attempt in range(retries + 1):

                async def _invoke() -> ExploreResult:
                    msgs: list[HumanMessage] = [HumanMessage(content=prompt)]
                    if attempt > 0:
                        msgs.append(self._synthesis_repair_message())
                    async with asyncio.timeout(timeout):
                        return await invoke_structured_chat_typed(
                            model,
                            msgs,
                            ExploreResult,
                            normalize=lambda data: self._normalize_synthesis_payload(
                                data,
                                search_target=search_target,
                            ),
                        )

                try:
                    return run_with_llm_call_policy_sync(_invoke, config=llm_config)
                except StructuredOutputError as exc:
                    last_exc = exc
                    if attempt < retries:
                        logger.warning(
                            "Explore: synthesis structured output invalid on %s model "
                            "(attempt %d/%d): %s",
                            model_name,
                            attempt + 1,
                            retries + 1,
                            exc,
                        )
                        continue
                    logger.warning(
                        "Explore: synthesis structured retries exhausted on %s model: %s",
                        model_name,
                        exc,
                    )
                    break
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Explore synthesis failed without a captured exception")

    async def _invoke_synthesis_llm_async(
        self, prompt: str, *, search_target: str
    ) -> ExploreResult:
        from soothe_nano.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )

        timeout = self._explore_config.synthesis_timeout_seconds
        llm_config = llm_rate_limit_config_from(self._soothe_config).model_copy(
            update={
                "call_timeout_seconds": max(int(timeout), 30),
                "call_timeout_max_seconds": max(int(timeout), 30),
            }
        )

        retries = max(0, int(self._explore_config.synthesis_validation_retries))
        models: list[tuple[str, BaseChatModel]] = [("synthesis", self._synthesis_model)]
        if (
            self._explore_config.synthesis_fallback_to_primary_model
            and not self._same_model_instance(self._synthesis_model, self._model)
        ):
            models.append(("primary", self._model))

        last_exc: Exception | None = None
        for model_name, model in models:
            for attempt in range(retries + 1):

                async def _invoke() -> ExploreResult:
                    msgs: list[HumanMessage] = [HumanMessage(content=prompt)]
                    if attempt > 0:
                        msgs.append(self._synthesis_repair_message())
                    async with asyncio.timeout(timeout):
                        return await invoke_structured_chat_typed(
                            model,
                            msgs,
                            ExploreResult,
                            normalize=lambda data: self._normalize_synthesis_payload(
                                data,
                                search_target=search_target,
                            ),
                        )

                try:
                    return await await_with_llm_call_policy(_invoke, config=llm_config)
                except StructuredOutputError as exc:
                    last_exc = exc
                    if attempt < retries:
                        logger.warning(
                            "Explore: synthesis structured output invalid on %s model "
                            "(attempt %d/%d): %s",
                            model_name,
                            attempt + 1,
                            retries + 1,
                            exc,
                        )
                        continue
                    logger.warning(
                        "Explore: synthesis structured retries exhausted on %s model: %s",
                        model_name,
                        exc,
                    )
                    break
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Explore synthesis failed without a captured exception")

    def _partial_synthesis_response(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
        current_iter: int,
        *,
        failure_reason: str,
        ai_message: str,
    ) -> ExtendedModelResponse[ExploreResult]:
        structured = build_explore_result_from_findings(
            findings,
            search_target=search_target,
            thoroughness=self._explore_config.thoroughness,
            max_matches=self._max_matches,
            status="partial",
            failure_reason=failure_reason,
        )
        return ExtendedModelResponse(
            model_response=ModelResponse(
                result=[AIMessage(content=ai_message)],
                structured_response=structured,
            ),
            command=Command(
                update={
                    "explore_model_invocations": current_iter + 1,
                    "prev_findings_count": len(findings),
                    "findings_stall_counter": 0,
                    "explore_completion_status": "partial",
                    "explore_failure_reason": failure_reason[:500],
                }
            ),
        )

    def _synthesize_findings(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
        current_iter: int,
        *,
        failure_reason: str = "",
    ) -> ExtendedModelResponse[ExploreResult]:
        """Synthesize findings into structured result (IG-399).

        Performance optimization (May 2026):
        - Uses fast model for synthesis (3x faster than default model)
        - Limits findings payload to configurable max (default 15, reduced from 20)
        - Truncates snippets to 100 chars (same as before)
        - Calculates relevance scores when semantic similarity enabled
        - Ranks findings by relevance before synthesis
        - Logs synthesis timing for performance monitoring
        """
        start_time = time.perf_counter()
        logger.info(
            "Explore: starting synthesis with %d findings (iter=%d)",
            len(findings),
            current_iter,
        )

        ranked = self._rank_findings_for_synthesis(findings, search_target)
        prompt, _detail_count = self._build_synthesis_prompt(ranked, search_target)

        completion_status = "complete"
        explore_failure = failure_reason
        try:
            structured = self._invoke_synthesis_llm_sync(prompt, search_target=search_target)
        except Exception as exc:
            reason = failure_reason or str(exc)
            logger.warning(
                "Explore: synthesis failed (%s); returning partial results from %d findings",
                reason,
                len(ranked),
                exc_info=True,
            )
            if not ranked:
                raise
            return self._partial_synthesis_response(
                ranked,
                search_target,
                current_iter,
                failure_reason=reason,
                ai_message="Returning partial explore results (synthesis failed).",
            )
        if ranked and not structured.matches:
            reason = "synthesis returned zero matches despite collected findings"
            logger.warning(
                "Explore: synthesis quality gate triggered (%s); returning deterministic complete result",
                reason,
            )
            completion_status = "complete"
            explore_failure = ""
            structured = build_explore_result_from_findings(
                ranked,
                search_target=search_target,
                thoroughness=self._explore_config.thoroughness,
                max_matches=self._max_matches,
                status="complete",
                failure_reason="",
            )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Explore: synthesis completed in %.1fs (%d findings → %d matches, status=%s)",
            elapsed,
            len(findings),
            len(structured.matches),
            completion_status,
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
                    "explore_completion_status": completion_status,
                    "explore_failure_reason": explore_failure[:500],
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
        messages = request.messages
        thread_ws = state.get("workspace") or self._resolver_workspace
        search_target = resolve_explore_search_target(messages, state.get("search_target"))
        messages, current, findings, new_findings_count, stall_counter = (
            self._prepare_model_turn_state(state, messages)
        )
        findings_so_far = ""
        if findings:
            findings_so_far = "\nFindings so far:\n" + "\n".join(
                f"- {f.get('path', 'unknown')}" for f in findings[:10]
            )

        early_stop_threshold = self._explore_config.early_stop_no_new_findings_turns
        if stall_counter >= early_stop_threshold and current > 0:
            logger.info(
                "Explore: early stop after %d turns with no new findings — synthesizing",
                stall_counter,
            )
            return await self._asynthesize_findings(findings, search_target, current)

        if current >= self._max_iterations:
            logger.info(
                "Explore: budget exhausted after %d model turns — synthesizing result",
                current,
            )
            return await self._asynthesize_findings(findings, search_target, current)

        body = format_explore_agent_system(
            search_target=search_target,
            workspace=thread_ws,
            thoroughness=self._explore_config.thoroughness,
            max_iterations=self._max_iterations,
            max_read_lines=self._explore_config.max_read_lines,
            findings_so_far=findings_so_far,
        )
        req = request.override(messages=messages, system_message=SystemMessage(content=body))
        try:
            response = await handler(req)
        except Exception as exc:
            if not findings:
                logger.error(
                    "Explore: model turn failed with no findings (%s)",
                    exc,
                    exc_info=True,
                )
                raise
            logger.warning(
                "Explore: model turn failed (%s); returning partial results from %d findings",
                exc,
                len(findings),
            )
            return await self._asynthesize_findings(
                findings,
                search_target,
                current,
                failure_reason=str(exc),
            )
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

    async def _asynthesize_findings(
        self,
        findings: list[dict[str, Any]],
        search_target: str,
        current_iter: int,
        *,
        failure_reason: str = "",
    ) -> ExtendedModelResponse[ExploreResult]:
        """Async synthesis with timeout and partial fallback."""
        start_time = time.perf_counter()
        logger.info(
            "Explore: starting synthesis with %d findings (iter=%d)",
            len(findings),
            current_iter,
        )
        ranked = await self._arank_findings_for_synthesis(findings, search_target)
        prompt, _detail_count = self._build_synthesis_prompt(ranked, search_target)
        try:
            structured = await self._invoke_synthesis_llm_async(
                prompt,
                search_target=search_target,
            )
        except Exception as exc:
            reason = failure_reason or str(exc)
            logger.warning(
                "Explore: synthesis failed (%s); returning partial results from %d findings",
                reason,
                len(ranked),
                exc_info=True,
            )
            if not ranked:
                raise
            return self._partial_synthesis_response(
                ranked,
                search_target,
                current_iter,
                failure_reason=reason,
                ai_message="Returning partial explore results (synthesis failed).",
            )
        completion_status = "complete"
        explore_failure = failure_reason
        if ranked and not structured.matches:
            reason = "synthesis returned zero matches despite collected findings"
            logger.warning(
                "Explore: synthesis quality gate triggered (%s); returning deterministic complete result",
                reason,
            )
            completion_status = "complete"
            explore_failure = ""
            structured = build_explore_result_from_findings(
                ranked,
                search_target=search_target,
                thoroughness=self._explore_config.thoroughness,
                max_matches=self._max_matches,
                status="complete",
                failure_reason="",
            )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "Explore: synthesis completed in %.1fs (%d findings → %d matches, status=%s)",
            elapsed,
            len(findings),
            len(structured.matches),
            completion_status,
        )
        return ExtendedModelResponse(
            model_response=ModelResponse(
                result=[
                    AIMessage(content="Iteration budget reached; returning synthesized summary.")
                ],
                structured_response=structured,
            ),
            command=Command(
                update={
                    "explore_model_invocations": current_iter + 1,
                    "prev_findings_count": len(findings),
                    "findings_stall_counter": 0,
                    "explore_completion_status": completion_status,
                    "explore_failure_reason": explore_failure[:500],
                }
            ),
        )


class ExploreFinalizeMiddleware(AgentMiddleware[ExploreAgentState, None]):
    """Emit completion wire event and collapse messages to markdown delegate final."""

    state_schema = ExploreAgentState

    def __init__(
        self,
        *,
        thoroughness: str,
        max_matches: int,
    ) -> None:
        super().__init__()
        self._thoroughness = thoroughness
        self._max_matches = max_matches

    def after_agent(
        self,
        state: ExploreAgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        search_target = resolve_explore_search_target(
            messages,
            state.get("search_target"),
        )
        findings = state.get("findings") or []
        iterations_used = state.get("explore_model_invocations", 0)
        completion_status = str(state.get("explore_completion_status") or "complete")
        failure_reason = str(state.get("explore_failure_reason") or "")

        structured = state.get("structured_response")
        if structured is None:
            if findings:
                completion_status = "partial"
                failure_reason = failure_reason or "explore ended without structured synthesis"
                logger.warning(
                    "Explore: finalize recovery — %d findings, no structured_response (%s)",
                    len(findings),
                    failure_reason,
                )
                structured = build_explore_result_from_findings(
                    findings,
                    search_target=search_target,
                    thoroughness=self._thoroughness,
                    max_matches=self._max_matches,
                    status="partial",
                    failure_reason=failure_reason,
                )
            else:
                completion_status = "failed"
                failure_reason = failure_reason or "no findings collected"
                logger.error(
                    "Explore: failed with no findings (reason=%s)",
                    failure_reason,
                )
                md = (
                    "# Explore results\n\n"
                    "_Explore did not complete successfully; no findings were collected._\n"
                )
                if failure_reason:
                    md += f"\n**Reason:** {failure_reason}\n"
                emit_subagent_wire_event(
                    ExploreCompletedEvent(
                        total_findings=0,
                        thoroughness=self._thoroughness,
                        iterations_used=iterations_used,
                        duration_ms=0,
                        search_target=search_target,
                        completion_status=completion_status,
                        failure_reason=failure_reason,
                    ).to_dict(),
                    logger,
                )
                return {"messages": Overwrite([AIMessage(content=md)])}

        result = (
            structured
            if isinstance(structured, ExploreResult)
            else ExploreResult.model_validate(structured)
        )
        md = format_explore_result_markdown(result)
        started_at = state.get("explore_started_at_monotonic")
        if isinstance(started_at, (int, float)) and started_at > 0:
            elapsed_ms = max(0, int((time.perf_counter() - float(started_at)) * 1000))
        else:
            elapsed_ms = 0
        emit_subagent_wire_event(
            ExploreCompletedEvent(
                total_findings=len(findings),
                thoroughness=self._thoroughness,
                iterations_used=iterations_used,
                duration_ms=elapsed_ms,
                search_target=search_target,
                completion_status=completion_status,
                failure_reason=failure_reason,
            ).to_dict(),
            logger,
        )
        if completion_status == "partial":
            logger.warning(
                "Explore: completed partial result (%d findings, %d matches, %dms) reason=%s",
                len(findings),
                len(result.matches),
                elapsed_ms,
                failure_reason or "unknown",
            )
        elif completion_status == "failed":
            logger.error(
                "Explore: completed failed (%d findings, %d matches, %dms) reason=%s",
                len(findings),
                len(result.matches),
                elapsed_ms,
                failure_reason or "unknown",
            )
        else:
            logger.info(
                "Explore: completed %d matches in %dms (%d findings)",
                len(result.matches),
                elapsed_ms,
                len(findings),
            )
        updates: dict[str, Any] = {"messages": Overwrite([AIMessage(content=md)])}
        if completion_status != "complete":
            updates["structured_response"] = result
            updates["explore_completion_status"] = completion_status
            updates["explore_failure_reason"] = failure_reason
        return updates

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
    soothe_config: SootheConfig | None = None,
) -> list[AgentMiddleware[Any, None]]:
    """Ordered middleware list for ``create_agent`` (outermost first).

    Args:
        model: Primary model for exploration planning.
        explore_config: Explore-specific configuration.
        resolver_workspace: Resolver-provided workspace default.
        max_iterations: Maximum model turns before synthesis.
        max_matches: Maximum matches to return in result.
        synthesis_model: Optional fast model for synthesis (defaults to model).
        soothe_config: Optional SootheConfig for tool middleware (limits, retries).

    Returns:
        Middleware stack with tool limits, retries, budget, findings, wire, and finalize.
    """
    from langchain.agents.middleware import ToolCallLimitMiddleware, ToolRetryMiddleware

    # Build tool limit and retry middleware from config
    tool_middlewares: list[AgentMiddleware[Any, None]] = []
    if soothe_config is not None:
        mw = agent_middleware_config(soothe_config)
        thread_limit = (
            explore_config.tool_call_limit_thread or mw.tool_call_limit.global_thread_limit
        )
        run_limit = explore_config.tool_call_limit_run or mw.tool_call_limit.global_run_limit

        tool_middlewares.append(
            ToolCallLimitMiddleware(
                thread_limit=thread_limit,
                run_limit=run_limit,
                exit_behavior="continue",
            )
        )
        tool_middlewares.append(
            ToolRetryMiddleware(
                max_retries=mw.tool_retry.max_retries,
                backoff_factor=mw.tool_retry.backoff_factor,
                initial_delay=mw.tool_retry.initial_delay,
                on_failure="continue",
            )
        )

    from soothe_nano.middleware.tool_call_args_middleware import (
        ToolCallArgsMiddleware,
    )
    from soothe_nano.middleware.tool_optimization_middleware import (
        ToolOptimizationMiddleware,
    )

    return [
        # Tool call limit and retry middleware (outermost - applied first)
        *tool_middlewares,
        # IG-519: ToolCallArgsMiddleware records invocation args for subgraph tool display
        ToolCallArgsMiddleware(),
        # IG-653: deterministic lookup reuse/dedup/search consolidation in middleware layer
        ToolOptimizationMiddleware(),
        # Explore-specific middlewares
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
            soothe_config=soothe_config,
        ),
        ExploreFinalizeMiddleware(
            thoroughness=explore_config.thoroughness,
            max_matches=max_matches,
        ),
    ]
