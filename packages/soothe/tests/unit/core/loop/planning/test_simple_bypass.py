"""Tests for the shared expected-output contract (RFC-630).

The legacy ``SIMPLE_QUERY_DIRECT_PREFIX`` (``"I will complete this goal
directly:"``) and its ``startswith`` detector are removed (RFC-630). Only the
``## Result`` evidence contract survives, shared by the trivial-branch plan
(``build_trivial_plan`` in ``planning/trivial_plan.py``).
"""

from __future__ import annotations

from soothe.foundation.sloop.cognition.simple_bypass import (
    SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
    execute_deliverable_incomplete,
    expected_output_requires_result_block,
    output_contains_result_block,
)


def test_simple_query_expected_output_requires_result_block() -> None:
    """Bypass expected_output must force a `## Result` block so plan-assess
    sees concrete evidence in the ledger (trace 0e412f regression)."""
    assert "## Result" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "MUST" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "restate" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT.lower()


def test_execute_deliverable_incomplete_when_result_block_missing() -> None:
    assert execute_deliverable_incomplete(
        "Let me fetch that information for you.",
        SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
    )


def test_execute_deliverable_incomplete_when_result_block_present() -> None:
    assert not execute_deliverable_incomplete(
        "Done.\n\n## Result\n\nShanghai: sunny, 22°C",
        SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT,
    )


def test_execute_deliverable_incomplete_skips_non_contract_steps() -> None:
    assert not execute_deliverable_incomplete(
        "plain narration only",
        "Step completed successfully",
    )


def test_expected_output_requires_result_block_helper() -> None:
    assert expected_output_requires_result_block(SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT)
    assert not expected_output_requires_result_block("done")


def test_output_contains_result_block_helper() -> None:
    assert output_contains_result_block("## Result\n\nvalue")
    assert not output_contains_result_block("narration only")
