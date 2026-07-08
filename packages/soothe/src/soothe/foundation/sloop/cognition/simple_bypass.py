"""Expected-output contract shared by the trivial-branch plan (RFC-630).

The legacy ``SIMPLE_QUERY_DIRECT_PREFIX`` (``"I will complete this goal directly:"``)
and its ``startswith`` detector are removed (RFC-630): single-step goals are now
handled by the ``trivial`` intake label via ``build_trivial_plan`` in
``init_or_resume``, which emits the goal itself as the step action — no prefix.

Only the ``## Result`` evidence contract survives: it flows into the step's
user message ``expected_output``, which the LLM treats as the step's completion
contract. The ``## Result`` requirement forces the final assistant message to
restate the answer in plain text so goal completion can surface concrete evidence
from the ledger rather than only narration about tool calls.
"""

from __future__ import annotations

_RESULT_BLOCK_MARKER = "## Result"

SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT = (
    "Final assistant message MUST end with a Markdown block:\n"
    "## Result\n"
    "Answer that directly satisfies the user's request, "
    "including any numbers, paths, or names from tool output\n\n"
    "Do NOT summarize away the data — restate it here so it appears in the "
    "ledger. Omit this block only if the request is purely conversational "
    "(greeting, thanks)."
)

EXECUTE_ACTION_RETRY_NUDGE = (
    "You must call the appropriate tool(s) to gather the data before answering. "
    "Do not respond with narration alone. When done, end with the required "
    "## Result block including concrete numbers, paths, or names from tool output."
)


def expected_output_requires_result_block(expected_output: str | None) -> bool:
    """Return True when the step contract references the ``## Result`` deliverable."""
    return _RESULT_BLOCK_MARKER in (expected_output or "")


def output_contains_result_block(output: str | None) -> bool:
    """Return True when execute output includes a ``## Result`` section."""
    return _RESULT_BLOCK_MARKER in (output or "")


def execute_deliverable_incomplete(output: str | None, expected_output: str | None) -> bool:
    """Return True when an action step finished without the required ``## Result`` block."""
    if not expected_output_requires_result_block(expected_output):
        return False
    return not output_contains_result_block(output)


__all__ = [
    "EXECUTE_ACTION_RETRY_NUDGE",
    "SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT",
    "execute_deliverable_incomplete",
    "expected_output_requires_result_block",
    "output_contains_result_block",
]
