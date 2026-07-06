"""Integration tests for two-pass intake classification (RFC-630 IG-554).

Tests the full two-pass flow:
- Pass 1 (social vs task) with pivot pattern detection
- Pass 2 (scope classification) with prior projection
- Routing guard blocking chitchat on new_goal_created
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.sloop.intention import (
    IntakeLabel,
    IntakePass1Confidence,
    IntakePass1LLMResult,
    IntakePass2LLMResult,
    IntakeScope,
    TaskComplexity,
    TwoPassIntakeCoordinator,
)
from soothe.foundation.sloop.orchestrator.routing import route_by_intent

# -- Test fixtures ----------------------------------------------------------


def create_mock_coordinator(
    *,
    is_task: bool,
    confidence: str = "high",
    social_response: str | None = None,
    scope: str | None = None,
    goal_description: str | None = None,
    pass1_reasoning: str = "test",
    pass2_reasoning: str = "test",
) -> TwoPassIntakeCoordinator:
    """Create coordinator with mock that returns specified results."""
    mock_model = MagicMock()

    coordinator = TwoPassIntakeCoordinator(mock_model)

    # Mock the internal classifiers to return our expected results
    pass1_result = IntakePass1LLMResult(
        is_task=is_task,
        confidence=IntakePass1Confidence(confidence),
        social_response=social_response,
        reasoning=pass1_reasoning,
    )
    coordinator._pass1_classifier.classify = AsyncMock(return_value=pass1_result)

    # Always set up pass2 mock so we can track whether it was called
    pass2_result = IntakePass2LLMResult(
        scope=IntakeScope(scope) if scope else IntakeScope.COMPLEX,
        goal_description=goal_description or "test query",
        reasoning=pass2_reasoning,
    )
    coordinator._pass2_classifier.classify = AsyncMock(return_value=pass2_result)

    return coordinator


# -- Pass 1 integration tests -----------------------------------------------


@pytest.mark.asyncio
async def test_two_pass_pivot_pattern_routes_to_task() -> None:
    """Acknowledge+pivot patterns should route to task, not chitchat."""
    pivot_queries = [
        "Ok, now apply the fix",
        "Alright, so the tests...",
        "Got it, about the signature change",
        "Cool, and the migration script",
        "Sure, next: auth middleware",
    ]

    for query in pivot_queries:
        coordinator = create_mock_coordinator(
            is_task=True,
            confidence="high",
            scope="simple",
            goal_description=query,
            pass1_reasoning="pivot phrase detected",
        )
        result = await coordinator.classify(query)

        assert result.is_task is True, f"Query '{query}' should be task, not social"
        assert result.scope in (IntakeScope.TRIVIAL, IntakeScope.SIMPLE, IntakeScope.COMPLEX)


@pytest.mark.asyncio
async def test_two_pass_pure_greeting_routes_to_social() -> None:
    """Pure greetings without pivot should route to social."""
    greeting_queries = [
        "hi",
        "hello",
        "thanks!",
        "thank you",
        "who are you",
    ]

    for query in greeting_queries:
        coordinator = create_mock_coordinator(
            is_task=False,
            confidence="high",
            social_response="Hello! How can I help?",
            pass1_reasoning="greeting detected",
        )
        result = await coordinator.classify(query)

        assert result.is_social is True, f"Query '{query}' should be social"
        assert result.social_response is not None


@pytest.mark.asyncio
async def test_two_pass_standalone_acknowledgment_routes_to_social() -> None:
    """Standalone acknowledgment without pivot should be social."""
    standalone_ack_queries = [
        "ok",
        "sure",
        "alright",
        "got it",
        "perfect",
    ]

    for query in standalone_ack_queries:
        coordinator = create_mock_coordinator(
            is_task=False,
            confidence="high",
            social_response="Got it. What would you like to work on?",
            pass1_reasoning="standalone acknowledgment",
        )
        result = await coordinator.classify(query)

        assert result.is_social is True, f"Query '{query}' should be social (no pivot)"


# -- Pass 2 integration tests -----------------------------------------------


@pytest.mark.asyncio
async def test_two_pass_scope_trivial_for_simple_query() -> None:
    """Simple queries should get trivial scope."""
    coordinator = create_mock_coordinator(
        is_task=True,
        confidence="high",
        scope="trivial",
        goal_description="list files in src/",
        pass2_reasoning="single obvious action",
    )
    result = await coordinator.classify("list files in src/")

    assert result.is_task is True
    assert result.scope == IntakeScope.TRIVIAL
    assert result.intent_classification is not None
    assert result.intent_classification.intake_label == IntakeLabel.TRIVIAL


@pytest.mark.asyncio
async def test_two_pass_scope_complex_for_refactor() -> None:
    """Refactor queries should get complex scope."""
    coordinator = create_mock_coordinator(
        is_task=True,
        confidence="high",
        scope="complex",
        goal_description="Refactor SessionStore across all callers",
        pass2_reasoning="multi-file change",
    )
    result = await coordinator.classify("refactor SessionStore across all callers")

    assert result.is_task is True
    assert result.scope == IntakeScope.COMPLEX
    assert result.intent_classification.intake_label == IntakeLabel.COMPLEX


# -- Routing guard integration tests ----------------------------------------


def test_routing_guard_blocks_chitchat_on_new_goal_created() -> None:
    """Routing guard should force complex when new_goal_created=True."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
        "new_goal_created": True,
    }

    result = route_by_intent(state)
    assert result == "bounded_evidence_gather"


def test_routing_guard_allows_chitchat_on_resume() -> None:
    """Routing guard should allow chitchat when resuming existing goal."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
        "new_goal_created": False,
    }

    result = route_by_intent(state)

    from langgraph.graph import END

    assert result == END


# -- Full flow integration tests --------------------------------------------


@pytest.mark.asyncio
async def test_two_pass_creates_correct_intent_classification() -> None:
    """Two-pass result should produce valid IntentClassification for StrangeLoop."""
    coordinator = create_mock_coordinator(
        is_task=True,
        confidence="high",
        scope="simple",
        goal_description="Fix the type error in auth.py",
        pass2_reasoning="single file fix",
    )
    result = await coordinator.classify("fix the type error in auth.py")

    assert result.intent_classification is not None
    intent = result.intent_classification

    assert intent.intake_label == IntakeLabel.SIMPLE
    assert intent.goal_description == "Fix the type error in auth.py"
    assert intent.reasoning == "single file fix"
    assert intent.task_complexity == TaskComplexity.SIMPLE
    assert intent.chitchat_response is None


@pytest.mark.asyncio
async def test_two_pass_fail_safe_on_pass1_error() -> None:
    """Pass 1 error should fail-safe to task."""
    coordinator = TwoPassIntakeCoordinator(None)  # No model
    result = await coordinator.classify("any query")

    # Fail-safe: treat as task
    assert result.is_task is True
    assert result.pass1_confidence == "low"


@pytest.mark.asyncio
async def test_two_pass_prior_projection_used_for_scope() -> None:
    """Pass 2 should receive prior projection for reference resolution."""
    coordinator = create_mock_coordinator(
        is_task=True,
        confidence="high",
        scope="simple",
        goal_description="apply the signature change",
        pass2_reasoning="reference resolution from prior",
    )

    prior = "Previous goal: refactor SessionStore method signatures"
    result = await coordinator.classify("apply it", prior_projection=prior)

    assert result.is_task is True
    assert result.scope == IntakeScope.SIMPLE
    # Verify Pass 2 classifier was called (mock records this)
    assert coordinator._pass2_classifier.classify.called


# -- Edge case tests -------------------------------------------------------


@pytest.mark.asyncio
async def test_two_pass_identity_query_is_social() -> None:
    """Identity questions should be social, not task."""
    coordinator = create_mock_coordinator(
        is_task=False,
        confidence="high",
        social_response="I'm Soothe, created by Dr. Xiaming Chen.",
        pass1_reasoning="identity question",
    )
    result = await coordinator.classify("who are you")

    assert result.is_social is True
    assert "Soothe" in result.social_response or "Xiaming" in result.social_response


@pytest.mark.asyncio
async def test_two_pass_low_confidence_still_routes_to_task() -> None:
    """Low confidence in Pass 1 should still route to task."""
    coordinator = create_mock_coordinator(
        is_task=True,
        confidence="low",
        scope="complex",
        goal_description="ambiguous query",
        pass1_reasoning="ambiguous, fail-safe to task",
        pass2_reasoning="fail-safe complex",
    )
    result = await coordinator.classify("ambiguous input")

    # Low confidence still routes to task (fail-safe)
    assert result.is_task is True


@pytest.mark.asyncio
async def test_two_pass_social_response_preserved_for_chitchat() -> None:
    """Social response should be preserved for chitchat fast-path."""
    expected_response = "You're welcome! Let me know if you need anything else."

    coordinator = create_mock_coordinator(
        is_task=False,
        confidence="high",
        social_response=expected_response,
        pass1_reasoning="thanks",
    )
    result = await coordinator.classify("thanks!")

    assert result.is_social is True
    assert result.social_response == expected_response
    assert result.intent_classification is None  # No intent for social


@pytest.mark.asyncio
async def test_two_pass_no_pass2_for_social() -> None:
    """Pass 2 should not be called for social queries."""
    coordinator = create_mock_coordinator(
        is_task=False,
        confidence="high",
        social_response="Hello!",
        pass1_reasoning="greeting",
    )
    result = await coordinator.classify("hello")

    assert result.is_social is True
    # Pass 2 classifier should NOT have been called
    assert not coordinator._pass2_classifier.classify.called
