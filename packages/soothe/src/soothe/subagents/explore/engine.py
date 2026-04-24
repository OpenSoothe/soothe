"""Explore engine -- LLM-orchestrated iterative filesystem search (RFC-613).

Implements the search paradigm as a LangGraph:

  START → plan_search → execute_action → assess_results →
  [continue|adjust|finish] → synthesize → END

The LLM decides which tool to call at each step based on accumulated findings.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
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
from .tools import get_explore_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def build_explore_engine(
    model: BaseChatModel,
    config: ExploreSubagentConfig,
    workspace: str,
) -> Any:
    """Build and compile the explore LangGraph.

    Args:
        model: LLM for search planning, assessment, and synthesis.
        config: Explore configuration (thoroughness, iteration caps).
        workspace: Search boundary (working directory).

    Returns:
        Compiled LangGraph runnable.
    """
    # Get read-only filesystem tools
    tools = get_explore_tools()

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
        search_target = state.get("search_target", "")
        iterations_used = state.get("iterations_used", 0)
        findings = state.get("findings", [])

        # Emit started event on first iteration
        if iterations_used == 0:
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
            workspace=workspace,
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
            # Extract simple pattern from target
            fallback_pattern = f"**/*{search_target.split()[0]}*"
            from langchain_core.messages import ToolCall

            response = AIMessage(
                content=response.content,
                tool_calls=[
                    ToolCall(name="glob", args={"pattern": fallback_pattern}, id="fallback"),
                ],
            )

        return {"messages": [response]}

    def execute_action_node(state: ExploreState) -> dict[str, Any]:
        """Execute tool calls from plan_search."""
        messages = state.get("messages", [])
        if not messages:
            return {}

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            logger.warning("No tool calls to execute")
            return {}

        # Execute tools via ToolNode
        tool_results = tool_node.invoke({"messages": messages})

        # Extract results and update findings
        new_messages = tool_results.get("messages", [])
        findings_update: list[dict[str, Any]] = []

        for tool_msg in new_messages:
            if isinstance(tool_msg, ToolMessage):
                tool_name = tool_msg.name or "unknown"
                artifact = tool_msg.artifact

                # Extract paths from tool results
                if tool_name == "glob" and isinstance(artifact, list):
                    for path in artifact[:20]:  # Limit candidates
                        findings_update.append(
                            {"path": str(path), "snippet": None, "relevance": "unknown"}
                        )
                elif tool_name == "grep" and isinstance(artifact, list):
                    for match in artifact[:20]:
                        path = (
                            match.get("path", "unknown") if isinstance(match, dict) else str(match)
                        )
                        findings_update.append(
                            {"path": str(path), "snippet": None, "relevance": "unknown"}
                        )
                elif tool_name == "ls" and isinstance(artifact, list):
                    for item in artifact[:20]:
                        path = item if isinstance(item, str) else str(item)
                        findings_update.append(
                            {"path": path, "snippet": None, "relevance": "unknown"}
                        )
                elif tool_name == "read_file" and isinstance(artifact, str):
                    # If we read a file, we have content - add snippet
                    # Use current findings from state to get the last path
                    current_findings = state.get("findings", [])
                    if current_findings:
                        last_path = current_findings[-1].get("path", "")
                        findings_update.append(
                            {"path": last_path, "snippet": artifact[:500], "relevance": "unknown"}
                        )
                elif tool_name == "file_info":
                    # Metadata - could help assess relevance
                    pass

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
        search_target = state.get("search_target", "")
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
        iterations_used = state.get("iterations_used", 0)
        if iterations_used >= max_iterations:
            return "synthesize"

        decision = state.get("assessment_decision", "finish")
        if decision == "finish":
            return "synthesize"
        elif decision == "adjust":
            return "plan_search"
        else:  # "continue"
            return "execute_action"

    def synthesize_node(state: ExploreState) -> dict[str, Any]:
        """Synthesize final results."""
        search_target = state.get("search_target", "")
        findings = state.get("findings", [])
        iterations_used = state.get("iterations_used", 0)

        # Build findings detail
        findings_detail = (
            "\n".join(
                f"- {f.get('path', 'unknown')}: {f.get('snippet', '')[:100] or '(no snippet)'}"
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
        ["plan_search", "execute_action", "synthesize"],
    )
    graph.add_edge("synthesize", END)

    return graph.compile()
