"""Tests for semantic relationship detector (IG-433)."""

from unittest.mock import AsyncMock, patch

import pytest

from soothe.config.models import SemanticRelationshipsConfig
from soothe.foundation.autopilot.engine.models import Goal
from soothe.foundation.autopilot.engine.semantic_relationship_detector import (
    detect_relationships_async,
    detect_semantic_relationships,
)


def _goal(goal_id: str, description: str, status: str = "active") -> Goal:
    return Goal(
        id=goal_id,
        description=description,
        status=status,
        priority=50,
    )


@pytest.mark.asyncio
class TestDetectSemanticRelationships:
    async def test_high_similarity_informs(self) -> None:
        completed = _goal("g1", "Optimize database query performance for orders table")
        other = _goal("g2", "Improve orders table database query speed")

        with patch(
            "soothe.foundation.autopilot.engine.semantic_relationship_detector.async_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.88,
        ):
            relationships = await detect_semantic_relationships(
                completed,
                [completed, other],
                SemanticRelationshipsConfig(flag_threshold=0.7),
            )

        informs = [r for r in relationships if r.rel_type == "informs"]
        assert len(informs) == 1
        assert informs[0].from_goal == "g1"
        assert informs[0].to_goal == "g2"
        assert informs[0].confidence >= 0.7

    async def test_disabled_uses_legacy(self) -> None:
        completed = _goal("g1", "deploy production release")
        other = _goal("g2", "deploy staging release")

        relationships = await detect_relationships_async(
            completed,
            [completed, other],
            config=SemanticRelationshipsConfig(enabled=False),
        )
        assert isinstance(relationships, list)

    async def test_low_similarity_returns_empty(self) -> None:
        """Low similarity should return empty list (no keyword fallback)."""
        completed = _goal("g1", "alpha task one")
        other = _goal("g2", "beta task two")

        with patch(
            "soothe.foundation.autopilot.engine.semantic_relationship_detector.async_semantic_similarity",
            new_callable=AsyncMock,
            return_value=0.1,
        ):
            relationships = await detect_semantic_relationships(
                completed,
                [completed, other],
                SemanticRelationshipsConfig(flag_threshold=0.9),
            )

        # No relationships when similarity below threshold (no keyword fallback)
        assert relationships == []
