"""Generate structured metadata from tool results for Layer 2 reasoning.

This module extracts concise, structured metadata from tool execution results
to enable Layer 2 reasoning without full content bloat.

RFC-211: Layer 2 Tool Result Optimization
"""

from __future__ import annotations

import re
from typing import Any


def generate_outcome_metadata(tool_name: str, result: Any, tool_call_id: str) -> dict[str, Any]:
    """Generate structured outcome metadata from tool result.

    Args:
        tool_name: Name of the tool that was executed
        result: Tool execution result (string, dict, or list)
        tool_call_id: Unique identifier for this tool invocation

    Returns:
        Structured metadata dict for Layer 2 reasoning with fields:
        - type: Tool category (file_read, file_write, web_search, etc.)
        - tool_call_id: Unique identifier
        - tool_name: Tool name
        - success_indicators: Tool-specific metrics
        - entities: Key resources found/affected
        - size_bytes: Result size
        - file_ref: Optional cache reference for large results
    """
    outcome: dict[str, Any] = {
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
    }

    # Dispatch to tool-specific metadata extractors
    if tool_name in ["read_file", "ls", "grep", "glob"]:
        outcome["type"] = "file_read"
        outcome.update(_extract_file_metadata(result))
    elif tool_name in ["write_file", "edit_file"]:
        outcome["type"] = "file_write"
        outcome.update(_extract_file_write_metadata(result))
    elif tool_name in ["web_search", "tavily_search", "duckduckgo_search"]:
        outcome["type"] = "web_search"
        outcome.update(_extract_search_metadata(result))
    elif tool_name == "execute":
        outcome["type"] = "code_exec"
        outcome.update(_extract_exec_metadata(result))
    elif tool_name == "task":
        outcome["type"] = "subagent"
        outcome.update(_extract_subagent_metadata(result))
    else:
        outcome["type"] = "generic"
        outcome.update(_extract_generic_metadata(result))

    # Calculate size
    content_str = result if isinstance(result, str) else str(result)
    outcome["size_bytes"] = len(content_str.encode("utf-8"))

    return outcome


def _extract_file_metadata(result: Any) -> dict[str, Any]:
    """Extract metadata from file operation results.

    Args:
        result: File operation result

    Returns:
        Metadata dict with lines, files_found, entities
    """
    content = result if isinstance(result, str) else str(result)

    lines = content.count("\n") + 1 if content else 0

    # Extract file paths mentioned in result
    entities = _extract_file_paths(content)

    return {
        "success_indicators": {
            "lines": lines,
            "files_found": len(entities),
            "has_content": bool(content),
        },
        "entities": entities[:10],  # Limit to top 10
    }


def _extract_file_write_metadata(result: Any) -> dict[str, Any]:
    """Extract metadata from file write results.

    Args:
        result: File write operation result

    Returns:
        Metadata dict with written status, files_written, entities
    """
    content = result if isinstance(result, str) else str(result)

    # Parse success message
    success = "success" in content.lower() or "wrote" in content.lower() or "written" in content.lower()

    entities = _extract_file_paths(content)

    return {
        "success_indicators": {
            "written": success,
            "files_written": len(entities),
        },
        "entities": entities[:10],
    }


def _extract_search_metadata(result: Any) -> dict[str, Any]:
    """Extract metadata from web search results.

    Args:
        result: Web search result

    Returns:
        Metadata dict with results_count, domains_found, entities
    """
    content = result if isinstance(result, str) else str(result)

    # Count results (rough heuristic based on URLs)
    result_count = content.count("http://") + content.count("https://")

    # Extract domains
    domains = re.findall(r"https?://([^/]+)", content)
    unique_domains = list(set(domains))[:5]

    # Extract key terms from quoted strings
    entities = _extract_key_terms(content)

    return {
        "success_indicators": {
            "results_count": result_count,
            "domains_found": len(unique_domains),
        },
        "entities": unique_domains + entities[:5],
    }


def _extract_exec_metadata(result: Any) -> dict[str, Any]:
    """Extract metadata from code execution results.

    Args:
        result: Code execution result

    Returns:
        Metadata dict with exit_code, stdout_lines, has_error
    """
    content = result if isinstance(result, str) else str(result)

    # Parse exit code if present
    exit_code = 0
    if "exit code:" in content.lower() or "exit_code:" in content.lower():
        match = re.search(r"exit[_ ]?code:\s*(\d+)", content, re.IGNORECASE)
        if match:
            exit_code = int(match.group(1))

    # Count output lines
    stdout_lines = content.count("\n") + 1

    # Detect errors
    has_error = exit_code != 0 or "error" in content.lower()

    return {
        "success_indicators": {
            "exit_code": exit_code,
            "stdout_lines": stdout_lines,
            "has_error": has_error,
        },
        "entities": [],
    }


def _extract_subagent_metadata(result: Any) -> dict[str, Any]:
    """Extract metadata from subagent delegation results.

    Args:
        result: Subagent task result

    Returns:
        Metadata dict with completed status, artifacts_created, entities
    """
    content = result if isinstance(result, str) else str(result)

    # Extract artifacts mentioned (files created/modified)
    entities = _extract_file_paths(content)

    # Detect completion status
    completed = "completed" in content.lower() or "finished" in content.lower() or "done" in content.lower()

    return {
        "success_indicators": {
            "completed": completed,
            "artifacts_created": len(entities),
        },
        "entities": entities[:10],
    }


def _extract_generic_metadata(result: Any) -> dict[str, Any]:
    """Extract generic metadata for unknown tool types.

    Args:
        result: Generic tool result

    Returns:
        Metadata dict with basic success indicator
    """
    content = result if isinstance(result, str) else str(result)

    return {
        "success_indicators": {
            "has_output": bool(content),
        },
        "entities": [],
    }


def _extract_file_paths(text: str) -> list[str]:
    """Extract file paths from text.

    Args:
        text: Text to search for file paths

    Returns:
        List of file paths found (up to 10)
    """
    # Match file paths (simplified patterns)
    patterns = [
        r"/[\w\-./]+\.\w+",  # Absolute paths with extension
        r"[\w\-./]+\.\w{2,4}",  # Relative paths with common extensions
    ]

    paths = []
    for pattern in patterns:
        paths.extend(re.findall(pattern, text))

    # Remove duplicates and return top 10
    seen = set()
    unique_paths = []
    for path in paths:
        if path not in seen and not path.startswith("http"):  # Exclude URLs
            seen.add(path)
            unique_paths.append(path)

    return unique_paths[:10]


def _extract_key_terms(text: str) -> list[str]:
    """Extract key terms/entities from text.

    Args:
        text: Text to search for key terms

    Returns:
        List of quoted strings found (up to 5)
    """
    # Extract quoted strings
    quoted = re.findall(r'"([^"]+)"', text)
    quoted.extend(re.findall(r"'([^']+)'", text))

    return quoted[:5]
