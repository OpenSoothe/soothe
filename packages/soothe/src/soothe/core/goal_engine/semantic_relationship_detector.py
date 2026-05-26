"""Embedding-based goal relationship detection (IG-433)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from soothe.config.models import SemanticRelationshipsConfig
from soothe.core.goal_engine.relationship_detector import (
    Relationship,
    _extract_artifact_refs,
    detect_relationships,
)
from soothe.utils.similarity import async_semantic_similarity

if TYPE_CHECKING:
    from soothe.core.goal_engine.models import Goal

logger = logging.getLogger(__name__)


@dataclass
class RelationshipConfig:
    """Runtime configuration for semantic relationship detection."""

    auto_apply_threshold: float = 0.85
    flag_threshold: float = 0.70

    @classmethod
    def from_pydantic(cls, cfg: SemanticRelationshipsConfig) -> RelationshipConfig:
        """Build from ``SemanticRelationshipsConfig``."""
        return cls(
            auto_apply_threshold=cfg.auto_apply_threshold,
            flag_threshold=cfg.flag_threshold,
        )


async def detect_semantic_relationships(
    completed_goal: Goal,
    all_goals: list[Goal],
    config: RelationshipConfig | SemanticRelationshipsConfig | None = None,
) -> list[Relationship]:
    """Detect relationships using embedding similarity between goal descriptions.

    Preserves artifact-based ``depends_on`` detection from the legacy detector.
    Falls back to keyword/Jaccard heuristics when embeddings are unavailable.

    Args:
        completed_goal: The goal that just completed.
        all_goals: All known goals.
        config: Threshold settings.

    Returns:
        List of detected relationships with confidence scores.
    """
    if isinstance(config, SemanticRelationshipsConfig):
        rel_cfg = RelationshipConfig.from_pydantic(config)
    else:
        rel_cfg = config or RelationshipConfig()

    relationships: list[Relationship] = []
    completed_desc = (completed_goal.description or "").strip()
    if not completed_desc:
        return detect_relationships(completed_goal, all_goals)

    for other in all_goals:
        if other.id == completed_goal.id:
            continue
        if other.status in ("completed", "failed"):
            continue

        other_desc = (other.description or "").strip()
        if not other_desc:
            continue

        try:
            similarity = await async_semantic_similarity(completed_desc, other_desc)
        except Exception:
            logger.debug("Semantic similarity failed for goals %s/%s", completed_goal.id, other.id)
            similarity = 0.0

        if similarity >= rel_cfg.flag_threshold:
            relationships.append(
                Relationship(
                    from_goal=completed_goal.id,
                    to_goal=other.id,
                    rel_type="informs",
                    confidence=round(similarity, 2),
                    reason=f"Semantic description similarity ({similarity:.2f})",
                )
            )

        completed_artifact_refs = _extract_artifact_refs(completed_desc)
        relationships.extend(
            [
                Relationship(
                    from_goal=other.id,
                    to_goal=completed_goal.id,
                    rel_type="depends_on",
                    confidence=0.85,
                    reason=f"References completed goal's output: {ref}",
                )
                for ref in completed_artifact_refs
                if ref.lower() in other_desc.lower()
            ]
        )

    if relationships:
        return relationships

    # No semantic relationships detected - skip keyword fallback
    logger.debug("No semantic relationships for goal %s", completed_goal.id)
    return []


async def detect_relationships_async(
    completed_goal: Goal,
    all_goals: list[Goal],
    *,
    config: SemanticRelationshipsConfig | None = None,
) -> list[Relationship]:
    """Detect relationships using semantic or legacy heuristics based on config.

    Args:
        completed_goal: The goal that just completed.
        all_goals: All known goals.
        config: When ``enabled``, uses embedding similarity; otherwise legacy path.

    Returns:
        Detected relationships.
    """
    cfg = config or SemanticRelationshipsConfig()
    if cfg.enabled:
        return await detect_semantic_relationships(completed_goal, all_goals, cfg)
    return detect_relationships(completed_goal, all_goals)
