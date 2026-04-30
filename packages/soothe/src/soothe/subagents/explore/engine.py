"""Explore engine -- LLM-orchestrated iterative filesystem search (RFC-613).

Implements the search paradigm as a LangGraph:

  START → plan_search → execute_action → assess_results →
  (finish | budget → synthesize; continue | adjust → plan_search) → … → END

The LLM decides which tool to call at each step based on accumulated findings.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from soothe.utils.progress import emit_progress

from .events import (
    ExploreAssessingEvent,
    ExploreCompletedEvent,
    ExploreExecutingEvent,
    ExploreStartedEvent,
)
from .prompts import ASSESS_RESULTS, PLAN_SEARCH, SYNTHESIZE
from .schemas import ExploreResult, ExploreState, ExploreSubagentConfig
from .search_target import resolve_explore_search_target
from .tools import get_explore_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def route_after_explore_assessment(
    iterations_used: int,
    max_iterations: int,
    assessment_decision: str | None,
) -> Literal["plan_search", "synthesize"]:
    """Next node after assess: finish or budget → synthesize; else replan.

    ``continue``/``adjust`` must return ``plan_search`` so the model emits a new
    ``AIMessage`` with tool calls. After ``execute_action``, ``messages[-1]`` is
    a ``ToolMessage``, so routing ``continue`` to ``execute_action`` no-ops (IG-326).
    """
    if iterations_used >= max_iterations:
        return "synthesize"
    decision = (assessment_decision or "finish").lower()
    if decision not in ("continue", "adjust", "finish"):
        decision = "finish"
    if decision == "finish":
        return "synthesize"
    return "plan_search"


def pending_tool_ai_index_and_message(messages: list[Any]) -> tuple[int, AIMessage] | None:
    """Find the newest AIMessage with tool calls that still lacks tool results.

    After ``execute_action``, trailing messages are ``ToolMessage``s, so
    ``messages[-1]`` is not an ``AIMessage``. The next ``plan_search`` appends a
    new ``AIMessage``; until that merge is visible, or if ordering differs, we
    must not assume the last list element is the planner message (IG-326).

    Scans from the end of ``messages`` for each ``AIMessage`` with ``tool_calls``
    and returns the first (i.e. chronologically latest) whose tool call ids are
    not all matched by following ``ToolMessage`` instances after that index.

    Args:
        messages: Full LangGraph ``messages`` channel value.

    Returns:
        ``(index, ai_message)`` for pending execution, or ``None`` if none.
    """
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if not isinstance(m, AIMessage) or not m.tool_calls:
            continue
        ids = {str(tc.get("id")) for tc in m.tool_calls if tc.get("id")}
        if not ids:
            continue
        answered = {
            str(tm.tool_call_id)
            for tm in messages[i + 1 :]
            if isinstance(tm, ToolMessage) and tm.tool_call_id is not None
        }
        if ids - answered:
            return (i, m)
    return None


def build_explore_engine(
    model: BaseChatModel,
    config: ExploreSubagentConfig,
    workspace: str,
    *,
    allow_paths_outside_workspace: bool = False,
) -> Any:
    """Build and compile the explore LangGraph.

    Args:
        model: LLM for search planning, assessment, and synthesis.
        config: Explore configuration (thoroughness, iteration caps).
        workspace: Search boundary (working directory).
        allow_paths_outside_workspace: When False, sandbox tools to *workspace*.

    Returns:
        Compiled LangGraph runnable.
    """
    # Get read-only filesystem tools (reusing deepagents tools)
    # Note: workspace parameter is initial/resolver workspace; thread workspace
    # overrides at runtime via state.workspace (IG-328). Tools will re-resolve
    # paths at execution time.
    tools = get_explore_tools(
        workspace=workspace,
        allow_paths_outside_workspace=allow_paths_outside_workspace,
    )

    # Bind tools to model for plan_search node
    model_with_tools = model.bind_tools(tools)

    # Create ToolNode for execute_action node
    tool_node = ToolNode(tools)

    # Resolve max_iterations based on thoroughness
    thoroughness = config.thoroughness
    max_iterations = config.max_iterations.get(thoroughness, 4)
    max_matches = config.max_matches_returned
    max_read_lines = config.max_read_lines

    def plan_search_node(state: ExploreState) -> dict[str, Any]:
        """Plan next search action via LLM."""
        messages = state.get("messages") or []
        explicit = state.get("search_target")
        search_target = resolve_explore_search_target(messages, explicit)
        iterations_used = state.get("iterations_used", 0)
        findings = state.get("findings", [])

        # Use thread workspace from state (runtime injection), fallback to resolver workspace (IG-328)
        thread_workspace = state.get("workspace") or workspace
        if thread_workspace != workspace:
            logger.debug(
                "Explore: using thread workspace '%s' (resolver='%s')",
                thread_workspace,
                workspace,
            )

        # Emit started event on first iteration
        if iterations_used == 0:
            logger.info("Explore: searching for '%s'", search_target[:80])
            emit_progress(
                ExploreStartedEvent(
                    search_target=search_target[:200],
                    thoroughness=thoroughness,
                ).to_dict(),
                logger,
            )

        # Build findings summary for prompt
        findings_so_far = ""
        if findings:
            findings_so_far = "\nFindings so far:\n" + "\n".join(
                f"- {f.get('path', 'unknown')}" for f in findings[:10]
            )

        prompt = PLAN_SEARCH.format(
            search_target=search_target,
            workspace=thread_workspace,
            thoroughness=thoroughness,
            max_iterations=max_iterations,
            max_read_lines=max_read_lines,
            findings_so_far=findings_so_far,
        )

        # Call LLM with tools bound
        response = model_with_tools.invoke([HumanMessage(content=prompt)])

        # If no tool calls, fallback to generic glob
        if not response.tool_calls:
            logger.warning("LLM did not produce tool calls, using fallback glob")
            words = search_target.split()
            first = words[0] if words else ""
            fallback_pattern = f"**/*{first}*" if first else "**/*"

            response = AIMessage(
                content=response.content,
                tool_calls=[
                    ToolCall(name="glob", args={"pattern": fallback_pattern}, id="fallback"),
                ],
            )

        logger.info("Explore: planned %d tools", len(response.tool_calls))

        out: dict[str, Any] = {"messages": [response]}
        # Persist target for assess/synthesize when task tool only set HumanMessage (IG-326).
        prior = explicit if isinstance(explicit, str) else ""
        if search_target and not prior.strip():
            out["search_target"] = search_target
        return out

    def execute_action_node(state: ExploreState) -> dict[str, Any]:
        """Execute tool calls from plan_search."""
        messages = state.get("messages", [])
        if not messages:
            return {}

        pending = pending_tool_ai_index_and_message(messages)
        if pending is None:
            logger.warning(
                "No pending AIMessage with tool calls to execute (tail=%s)",
                type(messages[-1]).__name__ if messages else "empty",
            )
            return {}

        pending_idx, last_message = pending
        # Prefix through pending AI so ToolNode does not pick an older, already-answered AIMessage.
        tool_messages_input = messages[: pending_idx + 1]

        # Execute tools via ToolNode
        logger.info("Explore: executing tools")
        tool_results = tool_node.invoke({"messages": tool_messages_input})

        # Extract results and update findings
        new_messages = tool_results.get("messages", [])
        findings_update: list[dict[str, Any]] = []

        id_to_args: dict[str, dict[str, Any]] = {}
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            for tc in last_message.tool_calls:
                cid = tc.get("id")
                if cid:
                    args = tc.get("args")
                    id_to_args[str(cid)] = args if isinstance(args, dict) else {}

        for tool_msg in new_messages:
            if isinstance(tool_msg, ToolMessage):
                tool_name = tool_msg.name or "unknown"

                # Extract result data from ToolMessage (IG-327).
                # ToolNode populates content (not artifact) for most tools.
                # Prefer artifact if explicitly set, else use content.
                result_data = (
                    tool_msg.artifact if tool_msg.artifact is not None else tool_msg.content
                )

                # Extract paths from tool results
                if tool_name == "glob":
                    # glob returns list[str] paths
                    paths: list[str] = []
                    if isinstance(result_data, list):
                        paths = [str(p) for p in result_data[:20]]
                    elif isinstance(result_data, str) and result_data.strip():
                        # Fallback: split by newline if string
                        paths = [
                            p.strip() for p in result_data.strip().split("\n")[:20] if p.strip()
                        ]
                    for path in paths:
                        findings_update.append(
                            {"path": path, "snippet": None, "relevance": "unknown"}
                        )
                    logger.debug("Explore: glob found %d paths", len(paths))

                elif tool_name == "grep":
                    # grep returns list[dict] matches with path field
                    matches: list[Any] = []
                    if isinstance(result_data, list):
                        matches = result_data[:20]
                    elif isinstance(result_data, str) and result_data.strip():
                        # Fallback: parse grep output format
                        lines = result_data.strip().split("\n")[:20]
                        for line in lines:
                            if ":" in line:
                                path_part = line.split(":")[0].strip()
                                if path_part:
                                    matches.append({"path": path_part})
                    for match in matches:
                        path = (
                            match.get("path", "unknown") if isinstance(match, dict) else str(match)
                        )
                        findings_update.append(
                            {"path": str(path), "snippet": None, "relevance": "unknown"}
                        )
                    logger.debug("Explore: grep found %d matches", len(matches))

                elif tool_name == "ls":
                    # ls returns list[str] entries
                    entries: list[str] = []
                    if isinstance(result_data, list):
                        entries = [str(e) for e in result_data[:20]]
                    elif isinstance(result_data, str) and result_data.strip():
                        entries = [
                            e.strip() for e in result_data.strip().split("\n")[:20] if e.strip()
                        ]
                    for path in entries:
                        findings_update.append(
                            {"path": path, "snippet": None, "relevance": "unknown"}
                        )
                    logger.debug("Explore: ls found %d entries", len(entries))

                elif tool_name == "read_file":
                    # read_file returns str content
                    content_str = ""
                    if isinstance(result_data, str):
                        content_str = result_data
                    elif result_data is not None:
                        content_str = str(result_data)
                    if content_str.strip():
                        # Use path from prior finding or tool args
                        current_findings = state.get("findings", [])
                        last_path = current_findings[-1].get("path", "") if current_findings else ""
                        if not last_path:
                            # Try to get path from tool args
                            args = id_to_args.get(str(tool_msg.tool_call_id or ""), {})
                            last_path = str(
                                args.get("file_path", "") or args.get("path", "") or "unknown"
                            )
                        findings_update.append(
                            {
                                "path": last_path,
                                "snippet": content_str[:500],
                                "relevance": "unknown",
                            }
                        )
                        logger.debug(
                            "Explore: read_file %s (%d chars)", last_path, len(content_str)
                        )

                elif tool_name == "file_info":
                    args = id_to_args.get(str(tool_msg.tool_call_id or ""), {})
                    path = str(args.get("path", "") or "unknown")
                    snippet: str | None = None
                    if isinstance(result_data, str) and result_data.strip():
                        snippet = result_data.strip()[:500]
                    if path != "unknown" or snippet:
                        findings_update.append(
                            {"path": path, "snippet": snippet, "relevance": "unknown"}
                        )

                emit_progress(
                    ExploreExecutingEvent(
                        tool_name=tool_name,
                        results_count=len(findings_update),
                    ).to_dict(),
                    logger,
                )

        return {
            "messages": new_messages,
            "findings": findings_update,
            "iterations_used": state.get("iterations_used", 0) + 1,
        }

    def assess_results_node(state: ExploreState) -> dict[str, Any]:
        """Assess whether findings are sufficient."""
        search_target = resolve_explore_search_target(
            state.get("messages") or [],
            state.get("search_target"),
        )
        findings = state.get("findings", [])
        iterations_used = state.get("iterations_used", 0)

        # Force finish if budget exceeded
        if iterations_used >= max_iterations:
            decision = "finish"
        else:
            # Build findings summary
            findings_summary = (
                "\n".join(f"- {f.get('path', 'unknown')}" for f in findings[:10]) or "None"
            )

            prompt = ASSESS_RESULTS.format(
                search_target=search_target,
                findings_summary=findings_summary,
                iterations_used=iterations_used,
                max_iterations=max_iterations,
            )

            # Use structured output for decision
            from pydantic import BaseModel

            class AssessmentResult(BaseModel):
                decision: str

            structured_model = model.with_structured_output(AssessmentResult)
            result = structured_model.invoke([HumanMessage(content=prompt)])
            decision = result.decision.lower()

            # Validate decision
            if decision not in ("continue", "adjust", "finish"):
                decision = "finish"

        logger.info(
            "Explore: decision=%s (iter %d/%d, found %d)",
            decision,
            iterations_used,
            max_iterations,
            len(findings),
        )

        emit_progress(
            ExploreAssessingEvent(
                decision=decision,
                findings_count=len(findings),
                iterations_used=iterations_used,
            ).to_dict(),
            logger,
        )

        return {"assessment_decision": decision}

    def route_after_assessment(state: ExploreState) -> str:
        """Route based on LLM assessment and iteration budget."""
        return route_after_explore_assessment(
            state.get("iterations_used", 0),
            max_iterations,
            state.get("assessment_decision"),
        )

    def synthesize_node(state: ExploreState) -> dict[str, Any]:
        """Synthesize final results."""
        search_target = resolve_explore_search_target(
            state.get("messages") or [],
            state.get("search_target"),
        )
        findings = state.get("findings", [])
        iterations_used = state.get("iterations_used", 0)

        # Build findings detail
        findings_detail = (
            "\n".join(
                f"- {f.get('path', 'unknown')}: {(f.get('snippet') or '')[:100] or '(no snippet)'}"
                for f in findings[:20]
            )
            or "No findings"
        )

        prompt = SYNTHESIZE.format(
            search_target=search_target,
            findings_detail=findings_detail,
            max_matches=max_matches,
        )

        start_time = time.perf_counter()

        # Use structured output for final result
        structured_model = model.with_structured_output(ExploreResult)
        result = structured_model.invoke([HumanMessage(content=prompt)])

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        emit_progress(
            ExploreCompletedEvent(
                total_findings=len(findings),
                thoroughness=thoroughness,
                iterations_used=iterations_used,
                duration_ms=elapsed_ms,
            ).to_dict(),
            logger,
        )

        logger.info("Explore: completed %d matches in %dms", len(result.matches), elapsed_ms)

        # Return final result as AIMessage
        return {"messages": [AIMessage(content=json.dumps(result.model_dump(), indent=2))]}

    # Build the graph
    graph = StateGraph(ExploreState)

    graph.add_node("plan_search", plan_search_node)
    graph.add_node("execute_action", execute_action_node)
    graph.add_node("assess_results", assess_results_node)
    graph.add_node("synthesize", synthesize_node)

    graph.add_edge(START, "plan_search")
    graph.add_edge("plan_search", "execute_action")
    graph.add_edge("execute_action", "assess_results")
    graph.add_conditional_edges(
        "assess_results",
        route_after_assessment,
        ["plan_search", "synthesize"],
    )
    graph.add_edge("synthesize", END)

    return graph.compile()
