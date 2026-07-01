"""Expected-output contract shared by the trivial-branch plan (RFC-630).

The legacy ``SIMPLE_QUERY_DIRECT_PREFIX`` (``"I will complete this goal directly:"``)
and its ``startswith`` detector are removed (RFC-630): single-step goals are now
handled by the ``trivial`` intake label via ``build_trivial_plan`` in
``init_or_resume``, which emits the goal itself as the step action — no prefix.

Only the ``## Result`` evidence contract survives: it flows into the step's
user message ``expected_output``, which the LLM treats as the step's completion
contract. The ``## Result`` requirement forces the final assistant message to
restate the answer in plain text so ``plan_assess`` sees concrete evidence in
the ledger rather than only narration about tool calls.
"""

from __future__ import annotations

SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT = (
    "Final assistant message MUST end with a Markdown block:\n"
    "## Result\n"
    "Answer that directly satisfies the user's request, "
    "including any numbers, paths, or names from tool output\n\n"
    "Do NOT summarize away the data — restate it here so it appears in the "
    "ledger. Omit this block only if the request is purely conversational "
    "(greeting, thanks)."
)


__all__ = [
    "SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT",
]
