"""Tests for the shared expected-output contract (RFC-630).

The legacy ``SIMPLE_QUERY_DIRECT_PREFIX`` (``"I will complete this goal
directly:"``) and its ``startswith`` detector are removed (RFC-630). Only the
``## Result`` evidence contract survives, shared by the trivial-branch plan
(``build_trivial_plan`` in ``planning/trivial_plan.py``).
"""

from __future__ import annotations

from soothe.foundation.sloop.cognition.simple_bypass import SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT


def test_simple_query_expected_output_requires_result_block() -> None:
    """Bypass expected_output must force a `## Result` block so plan-assess
    sees concrete evidence in the ledger (trace 0e412f regression)."""
    assert "## Result" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "MUST" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT
    assert "restate" in SIMPLE_QUERY_DIRECT_EXPECTED_OUTPUT.lower()
