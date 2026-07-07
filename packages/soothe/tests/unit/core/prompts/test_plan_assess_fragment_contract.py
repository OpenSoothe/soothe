"""Contract tests for plan_assess_instructions.xml (RFC-227)."""

from __future__ import annotations

# Preload schemas via the loop package so the prompts package import order
# resolves cleanly during standalone collection (otherwise loading
# soothe.core.prompts triggers a circular import via soothe.config).
import soothe.foundation.sloop.state.schemas  # noqa: F401
from soothe.foundation.sloop.prompts.fragments import PLAN_ASSESS_INSTRUCTIONS_FRAGMENT

_FRAGMENT_TEXT = PLAN_ASSESS_INSTRUCTIONS_FRAGMENT


def test_fragment_documents_assessment_reasoning_field() -> None:
    text = _FRAGMENT_TEXT
    # Must list assessment_reasoning in the schema preamble.
    assert "assessment_reasoning" in text
    # Must have a dedicated section header for it.
    assert "**assessment_reasoning**" in text


def test_fragment_anchors_reasoning_on_prior_progress() -> None:
    text = _FRAGMENT_TEXT
    assert "PRIOR PROGRESS:" in text
    # Both phrasings of the prior_progress mention exist in the field section.
    assert "cite a tool that ran" in text or "evidence excerpt" in text


def test_fragment_mandates_full_goal_completion() -> None:
    text = _FRAGMENT_TEXT
    assert "Fulfill" in text and "GOAL:" in text
    assert "do not stop" in text or "do not mark done" in text
    assert "Multi-part goals" in text


def test_fragment_forbids_goal_restatement_in_guards() -> None:
    text = _FRAGMENT_TEXT
    # Look for the guard line we added.
    assert "Do NOT restate the user's request" in text


def test_fragment_preserves_existing_guards() -> None:
    text = _FRAGMENT_TEXT
    # Pre-existing guards must remain (regression check).
    assert 'NEVER status="done"' in text
    assert "without full-goal ledger evidence" in text


def test_plan_assess_fragment_size_guard() -> None:
    """Regression: condensed prompt must stay lean (was ~3700 bytes pre-condense)."""
    assert len(_FRAGMENT_TEXT) < 2800
