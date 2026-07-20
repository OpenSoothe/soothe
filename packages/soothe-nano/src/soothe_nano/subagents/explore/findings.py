"""Derive explore ``findings`` rows from readonly tool outputs (RFC-613)."""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

_EXPLORE_TOOL_NAMES = frozenset({"glob", "grep", "ls", "read_file", "file_info"})
_MAX_DISCOVERED_PATHS_PER_TOOL = 20
_MAX_FINDING_SNIPPET_CHARS = 800


def should_record_findings(tool_name: str) -> bool:
    """Return True if this tool contributes path/snippet evidence (not structured finals)."""
    return tool_name in _EXPLORE_TOOL_NAMES


def extract_findings_from_tool_result(
    request: ToolCallRequest,
    tool_msg: ToolMessage,
) -> list[dict[str, Any]]:
    """Map a single tool result to zero or more ``findings`` dicts.

    Args:
        request: Tool call request (args + state).
        tool_msg: Result message from the tool node.

    Returns:
        New finding rows to merge into state (reducer append).
    """
    tool_name = tool_msg.name or ""
    if not should_record_findings(tool_name):
        return []

    call = request.tool_call
    args = call.get("args") if isinstance(call, dict) else {}
    if not isinstance(args, dict):
        args = {}

    result_data = tool_msg.artifact if tool_msg.artifact is not None else tool_msg.content

    findings: list[dict[str, Any]] = []

    if tool_name == "glob":
        paths: list[str] = []
        if isinstance(result_data, list):
            paths = [str(p) for p in result_data[:_MAX_DISCOVERED_PATHS_PER_TOOL]]
        elif isinstance(result_data, str) and result_data.strip():
            paths = [
                p.strip()
                for p in result_data.strip().split("\n")[:_MAX_DISCOVERED_PATHS_PER_TOOL]
                if p.strip()
            ]
        for path in paths:
            findings.append({"path": path, "snippet": None, "relevance": "unknown"})

    elif tool_name == "grep":
        matches: list[Any] = []
        if isinstance(result_data, list):
            matches = result_data[:_MAX_DISCOVERED_PATHS_PER_TOOL]
        elif isinstance(result_data, str) and result_data.strip():
            lines = result_data.strip().split("\n")[:_MAX_DISCOVERED_PATHS_PER_TOOL]
            for line in lines:
                if ":" in line:
                    path_part = line.split(":")[0].strip()
                    if path_part:
                        matches.append({"path": path_part})
        for match in matches:
            path = match.get("path", "unknown") if isinstance(match, dict) else str(match)
            findings.append({"path": str(path), "snippet": None, "relevance": "unknown"})

    elif tool_name == "ls":
        entries: list[str] = []
        if isinstance(result_data, list):
            entries = [str(e) for e in result_data[:_MAX_DISCOVERED_PATHS_PER_TOOL]]
        elif isinstance(result_data, str) and result_data.strip():
            entries = [
                e.strip()
                for e in result_data.strip().split("\n")[:_MAX_DISCOVERED_PATHS_PER_TOOL]
                if e.strip()
            ]
        for path in entries:
            findings.append({"path": path, "snippet": None, "relevance": "unknown"})

    elif tool_name == "read_file":
        content_str = ""
        if isinstance(result_data, str):
            content_str = result_data
        elif result_data is not None:
            content_str = str(result_data)
        if content_str.strip():
            last_path = str(args.get("file_path", "") or args.get("path", "") or "unknown")
            findings.append(
                {
                    "path": last_path,
                    "snippet": content_str[:_MAX_FINDING_SNIPPET_CHARS],
                    "relevance": "unknown",
                }
            )

    elif tool_name == "file_info":
        path = str(args.get("path", "") or "unknown")
        snippet: str | None = None
        if isinstance(result_data, str) and result_data.strip():
            snippet = result_data.strip()[:_MAX_FINDING_SNIPPET_CHARS]
        if path != "unknown" or snippet:
            findings.append({"path": path, "snippet": snippet, "relevance": "unknown"})

    return findings
