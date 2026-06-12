"""Simple-query planner bypass helpers (direct single-step execution)."""

from __future__ import annotations

SIMPLE_QUERY_DIRECT_PREFIX = "I will complete this goal directly:"

# expected_output for bypass steps. Flows into the user message's
# EXECUTION HINTS: section, which the LLM treats as the step's completion
# contract. The "## Result" requirement forces the final assistant message
# to restate the answer in plain text so plan-assess sees concrete evidence
# in the ledger rather than only narration about tool calls.
SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT = (
    "Final assistant message MUST end with a Markdown block:\n"
    "## Result\n"
    "Answer that directly satisfies the user's request, "
    "including any numbers, paths, or names from tool output\n\n"
    "Do NOT summarize away the data — restate it here so it appears in the "
    "ledger. Omit this block only if the request is purely conversational "
    "(greeting, thanks)."
)


def format_simple_query_direct_next_action(goal: str) -> str:
    """User-facing plan line and step description for simple-query bypass."""
    return f"{SIMPLE_QUERY_DIRECT_PREFIX} {goal}"


def is_simple_query_direct_next_action(text: str | None) -> bool:
    """True when ``next_action`` is the synthetic simple-bypass direct-completion line."""
    return bool((text or "").strip().startswith(SIMPLE_QUERY_DIRECT_PREFIX))


__all__ = [
    "SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT",
    "SIMPLE_QUERY_DIRECT_PREFIX",
    "format_simple_query_direct_next_action",
    "is_simple_query_direct_next_action",
]
