"""ThreadRelationshipModule: Goal similarity computation and thread selection.

RFC-609 §95-172: Implements goal similarity hierarchy (exact > semantic > dependency)
and thread selection strategies for goal context construction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.embeddings import Embeddings

from soothe.cognition.goal_engine.models import ContextConstructionOptions, Goal

if TYPE_CHECKING:
    from soothe.persistence.thread_store import ThreadRecord


class ThreadRelationshipModule:
    """Thread relationship analysis for goal context construction.

    RFC-609 §95-172: Computes goal similarity and constructs context
    with thread ecosystem awareness using embedding integration.

    Args:
        embedding_model: LangChain Embeddings implementation for similarity computation.

    Attributes:
        _embedding_model: Embedding model instance.
        _embedding_cache: Cache for goal embeddings (optional performance optimization).
    """

    def __init__(self, embedding_model: Embeddings) -> None:
        """Initialize with embedding model for similarity computation.

        Args:
            embedding_model: LangChain Embeddings implementation
        """
        self._embedding_model: Embeddings = embedding_model
        # Cache for goal embeddings (optional performance optimization)
        self._embedding_cache: dict[str, list[float]] = {}

    def compute_similarity(self, goal_a: Goal, goal_b: Goal) -> float:
        """Goal similarity for thread clustering.

        Hierarchy (exact > semantic > dependency):
        - Level 1: Exact match (same goal_id) → 1.0
        - Level 2: Semantic similarity (embedding distance) → 0.0-0.99
        - Level 3: Dependency relationship (same DAG path) → 0.0-0.8

        Args:
            goal_a: First goal.
            goal_b: Second goal.

        Returns:
            Similarity score in range [0.0, 1.0].
        """
        # Level 1: Exact match
        if goal_a.id == goal_b.id:
            return 1.0

        # Level 2: Semantic similarity
        emb_a = self._get_or_compute_embedding(goal_a.description)
        emb_b = self._get_or_compute_embedding(goal_b.description)

        semantic_sim = self._cosine_similarity(emb_a, emb_b)

        # Note: Level 3 (dependency relationship) could be added here
        # if Goal DAG context is available. For now, we use semantic similarity.
        # Future enhancement: Check if both goals in same dependency chain

        return semantic_sim

    async def select_threads(
        self,
        current_goal: Goal,
        all_threads: list[ThreadRecord],
        goal_lookup: dict[str, Goal],
        options: ContextConstructionOptions,
    ) -> list[ThreadRecord]:
        """Select relevant threads based on goal similarity and strategy.

        Args:
            current_goal: Goal being executed.
            all_threads: Available thread records from persistence.
            goal_lookup: Dictionary of goals (goal_id → Goal) for similarity computation.
            options: Context construction options.

        Returns:
            Filtered thread list based on similarity and strategy.

        Process:
        1. Filter threads by same_goal_id if include_same_goal_threads=True
        2. Compute similarity for each thread's goal
        3. Filter by similarity_threshold if include_similar_goals=True
        4. Apply thread_selection_strategy (latest/all/best_performing)
        5. Return selected threads
        """
        # Filter by same goal ID
        same_goal_threads = [t for t in all_threads if t.goal_id == current_goal.id]

        # Filter by similar goals
        similar_threads = []
        if options.include_similar_goals:
            for thread in all_threads:
                if thread.goal_id == current_goal.id:
                    continue  # Already in same_goal_threads

                # Get thread's goal from goal_lookup
                thread_goal = goal_lookup.get(thread.goal_id)
                if not thread_goal:
                    continue

                similarity = self.compute_similarity(current_goal, thread_goal)
                if similarity >= options.similarity_threshold:
                    similar_threads.append(thread)

        # Combine threads
        candidate_threads = same_goal_threads if options.include_same_goal_threads else []
        candidate_threads.extend(similar_threads)

        # Apply selection strategy
        if options.thread_selection_strategy == "latest":
            # Return most recent thread
            if candidate_threads:
                # Assuming ThreadRecord has created_at field
                return [max(candidate_threads, key=lambda t: t.created_at)]
            return []

        elif options.thread_selection_strategy == "all":
            # Return all matching threads
            return candidate_threads

        elif options.thread_selection_strategy == "best_performing":
            # Return thread with highest success rate
            # Assuming ThreadRecord has success_rate or similar metric
            if candidate_threads:
                # For now, use latest as proxy for best_performing
                # Future: Add success_rate field to ThreadRecord
                return [max(candidate_threads, key=lambda t: t.created_at)]
            return []

        return []

    def _get_or_compute_embedding(self, text: str) -> list[float]:
        """Cache-enabled embedding retrieval.

        Args:
            text: Text to embed (goal description).

        Returns:
            Embedding vector.
        """
        if text in self._embedding_cache:
            return self._embedding_cache[text]

        embedding = self._embedding_model.embed_query(text)
        self._embedding_cache[text] = embedding
        return embedding

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            vec_a: First vector.
            vec_b: Second vector.

        Returns:
            Cosine similarity score in [0.0, 1.0].
        """
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a**2 for a in vec_a) ** 0.5
        norm_b = sum(b**2 for b in vec_b) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        similarity = dot_product / (norm_a * norm_b)

        # Clamp to [0.0, 1.0] range
        return max(0.0, min(1.0, similarity))
