"""Semantic similarity utilities for content scoring.

Provides reusable similarity calculation for:
- Explore findings relevance scoring
- Loop message similarity detection (future use)
- Content deduplication and ranking

Uses sentence_transformers when available, falls back to keyword matching.

Model Cache:
- ``SOOTHE_HF_CACHE`` env var overrides cache path (used in Docker builds)
- Default: ``~/.cache/soothe/models/huggingface``
- Use warmup_embedding_model() to pre-download models at daemon startup
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

# Timeout for embedding model calls (seconds)
_EMBEDDING_TIMEOUT_SECONDS = 10

# Thread pool for embedding calls (to avoid blocking async loop)
_embedding_executor: ThreadPoolExecutor | None = None

# Dedicated pool for one-time model download/load (avoids HF hub async client vs event-loop issues)
_model_load_executor: ThreadPoolExecutor | None = None


def hf_embedding_cache_dir() -> Path:
    """HuggingFace cache directory for the embedding model (shared across processes).

    Priority:
    1. ``SOOTHE_HF_CACHE`` env var (for Docker builds and custom paths)
    2. Default: ``~/.cache/soothe/models/huggingface``

    Docker builds pre-cache models in ``SOOTHE_HF_CACHE`` for faster startup.
    """
    env_cache = os.environ.get("SOOTHE_HF_CACHE")
    if env_cache:
        return Path(env_cache)

    return Path.home() / ".cache" / "soothe" / "models" / "huggingface"


# Check if sentence_transformers is available
_has_sentence_transformers = False
_transformer_model = None
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_model_loading_attempted = False

try:
    from sentence_transformers import SentenceTransformer

    _has_sentence_transformers = True
    logger.debug("sentence_transformers available, semantic similarity enabled")
except ImportError:
    logger.debug("sentence_transformers not available, falling back to keyword similarity")


def _get_transformer_model() -> SentenceTransformer | None:
    """Load transformer model (cached globally, loads on first call).

    Uses synchronous loading to avoid async client closure issues.
    The model is loaded on first actual use, not at import time.
    Models are cached under ``~/.cache/soothe/models/huggingface``.
    """
    global _transformer_model, _has_sentence_transformers, _model_loading_attempted

    if not _has_sentence_transformers:
        return None

    if _model_loading_attempted:
        # Already tried loading, use cached result (may be None if failed)
        return _transformer_model

    _model_loading_attempted = True
    try:
        cache_dir = hf_embedding_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)

        def _load_in_worker() -> SentenceTransformer:
            return SentenceTransformer(
                EMBEDDING_MODEL_NAME,
                cache_folder=str(cache_dir),
            )

        # Load off the asyncio loop: HuggingFace hub can otherwise raise
        # "Cannot send a request, as the client has been closed" in mixed async/sync contexts.
        global _model_load_executor
        if _model_load_executor is None:
            _model_load_executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="st_model_load",
            )
        _transformer_model = _model_load_executor.submit(_load_in_worker).result(timeout=300)
        logger.info(
            "Loaded sentence_transformers model: %s (cache: %s)",
            EMBEDDING_MODEL_NAME,
            cache_dir,
        )
    except Exception as e:
        logger.warning("Failed to load sentence_transformers model: %s", e)
        _has_sentence_transformers = False
        _transformer_model = None

    return _transformer_model


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector.
        vec2: Second vector.

    Returns:
        Similarity score in range [0, 1].
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


def semantic_similarity(
    text1: str,
    text2: str,
    *,
    max_length: int = 200,
) -> float:
    """Calculate semantic similarity between two texts.

    Uses sentence_transformers when available for accurate semantic matching.
    Falls back to keyword overlap when sentence_transformers is not installed.

    WARNING: This function uses synchronous model.encode() which can block.
    For async contexts, use async_semantic_similarity() which has timeout protection.

    Args:
        text1: First text.
        text2: Second text.
        max_length: Maximum text length for embedding (truncation).

    Returns:
        Similarity score in range [0, 1].
    """
    # Normalize and truncate
    text1 = (text1 or "").strip()[:max_length]
    text2 = (text2 or "").strip()[:max_length]

    if not text1 or not text2:
        return 0.0

    # Try semantic similarity with transformers
    model = _get_transformer_model()
    if model is not None:
        try:
            embeddings = model.encode([text1, text2])
            similarity = cosine_similarity(embeddings[0].tolist(), embeddings[1].tolist())
            return max(0.0, min(1.0, similarity))
        except Exception as e:
            logger.debug("Embedding similarity failed: %s, falling back to keywords", e)

    # Fallback: keyword overlap similarity
    return keyword_similarity(text1, text2)


async def async_semantic_similarity(
    text1: str,
    text2: str,
    *,
    max_length: int = 200,
    timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS,
) -> float:
    """Calculate semantic similarity with timeout protection for async contexts.

    Wraps the blocking model.encode() call in a thread pool executor with timeout.
    Falls back to keyword similarity on timeout or embedding failure.

    Args:
        text1: First text.
        text2: Second text.
        max_length: Maximum text length for embedding (truncation).
        timeout_seconds: Timeout for embedding call (default: 30s).

    Returns:
        Similarity score in range [0, 1].
    """
    # Normalize and truncate
    text1 = (text1 or "").strip()[:max_length]
    text2 = (text2 or "").strip()[:max_length]

    if not text1 or not text2:
        return 0.0

    # Try semantic similarity with transformers (async with timeout)
    model = _get_transformer_model()
    if model is not None:
        try:
            # Run blocking encode() in thread pool with timeout
            global _embedding_executor
            if _embedding_executor is None:
                _embedding_executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="embedding"
                )

            async with asyncio.timeout(timeout_seconds):
                embeddings = await asyncio.get_event_loop().run_in_executor(
                    _embedding_executor,
                    lambda: model.encode([text1, text2]),
                )
            similarity = cosine_similarity(embeddings[0].tolist(), embeddings[1].tolist())
            return max(0.0, min(1.0, similarity))
        except TimeoutError:
            logger.warning(
                "Embedding call timed out after %.1fs, falling back to keyword similarity",
                timeout_seconds,
            )
        except Exception as e:
            logger.debug("Embedding similarity failed: %s, falling back to keywords", e)

    # Fallback: keyword overlap similarity
    return keyword_similarity(text1, text2)


def keyword_similarity(text1: str, text2: str) -> float:
    """Calculate keyword overlap similarity (fallback when transformers unavailable).

    Args:
        text1: First text.
        text2: Second text.

    Returns:
        Similarity score in range [0, 1].
    """
    # Simple tokenization
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())

    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity: intersection / union
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union)


def calculate_relevance_score(
    finding: dict[str, Any],
    search_target: str,
    *,
    enable_semantic: bool = True,
    threshold_high: float = 0.7,
    threshold_medium: float = 0.4,
) -> str:
    """Calculate relevance score for an explore finding.

    Combines path heuristic and content similarity:
    - High path match → immediate "high" (fast path)
    - Medium path match → check content similarity (semantic path)
    - Low path match → "low" (skip expensive calculation)

    Args:
        finding: Finding dict with 'path' and 'snippet' keys.
        search_target: Original search target text.
        enable_semantic: Enable semantic similarity (requires sentence_transformers).
        threshold_high: Threshold for "high" relevance.
        threshold_medium: Threshold for "medium" relevance.

    Returns:
        Relevance string: "high", "medium", or "low".
    """
    path = finding.get("path", "")
    snippet = finding.get("snippet")

    # Fast path: path-based heuristic
    path_relevance = _path_heuristic_relevance(path, search_target)

    # If high path match, return immediately (avoid expensive similarity)
    if path_relevance == "high":
        return "high"

    # Medium path: check content similarity if snippet exists
    if snippet and path_relevance == "medium" and enable_semantic:
        try:
            similarity = semantic_similarity(snippet[:200], search_target)

            if similarity >= threshold_high:
                return "high"
            elif similarity >= threshold_medium:
                return "medium"
            else:
                return "low"
        except Exception as e:
            logger.debug("Similarity calculation failed: %s", e)
            return path_relevance

    # Low path: no snippet or semantic disabled
    return path_relevance


def _path_heuristic_relevance(path: str, search_target: str) -> str:
    """Quick path-based relevance heuristic.

    Args:
        path: File path.
        search_target: Search target text.

    Returns:
        "high", "medium", or "low".
    """
    # Extract keywords from search target
    keywords = _extract_keywords(search_target)

    # Count keyword matches in path
    path_lower = path.lower()
    matches = sum(1 for kw in keywords if kw.lower() in path_lower)

    if matches >= 3:
        return "high"
    elif matches >= 1:
        return "medium"
    else:
        return "low"


def _extract_keywords(text: str) -> list[str]:
    """Extract keywords from text (simple heuristic).

    Args:
        text: Input text.

    Returns:
        List of potential keywords.
    """
    # Split on common separators
    words = text.lower().split()

    # Filter: remove stop words and short tokens
    stop_words = {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "and",
        "or",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "find",
        "search",
        "locate",
        "show",
        "get",
        "all",
        "this",
        "that",
    }

    keywords = [
        word for word in words if len(word) >= 3 and word not in stop_words and word.isalnum()
    ]

    return keywords


def rank_by_similarity(
    items: list[dict[str, Any]],
    target: str,
    *,
    content_key: str = "snippet",
    enable_semantic: bool = True,
) -> list[dict[str, Any]]:
    """Rank items by similarity to target text.

    Generic utility for ranking findings, messages, or any content by relevance.

    Args:
        items: List of dicts with content.
        target: Target text to compare against.
        content_key: Key in dict containing content (default: "snippet").
        enable_semantic: Enable semantic similarity.

    Returns:
        Items sorted by relevance (highest first).
    """
    if not items:
        return items

    scored_items = []
    for item in items:
        content = str(item.get(content_key, "") or "")
        similarity = semantic_similarity(content[:200], target) if enable_semantic else 0.0
        scored_items.append((similarity, item))

    # Sort by similarity descending
    scored_items.sort(key=lambda x: x[0], reverse=True)

    return [item for _, item in scored_items]


async def async_calculate_relevance_score(
    finding: dict[str, Any],
    search_target: str,
    *,
    enable_semantic: bool = True,
    threshold_high: float = 0.7,
    threshold_medium: float = 0.4,
    timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS,
) -> str:
    """Calculate relevance score with async semantic similarity and timeout.

    Args:
        finding: Finding dict with 'path' and 'snippet' keys.
        search_target: Original search target text.
        enable_semantic: Enable semantic similarity (requires sentence_transformers).
        threshold_high: Threshold for "high" relevance.
        threshold_medium: Threshold for "medium" relevance.
        timeout_seconds: Timeout for embedding call.

    Returns:
        Relevance string: "high", "medium", or "low".
    """
    path = finding.get("path", "")
    snippet = finding.get("snippet")

    # Fast path: path-based heuristic
    path_relevance = _path_heuristic_relevance(path, search_target)

    # If high path match, return immediately (avoid expensive similarity)
    if path_relevance == "high":
        return "high"

    # Medium path: check content similarity if snippet exists
    if snippet and path_relevance == "medium" and enable_semantic:
        try:
            similarity = await async_semantic_similarity(
                snippet[:200], search_target, timeout_seconds=timeout_seconds
            )

            if similarity >= threshold_high:
                return "high"
            elif similarity >= threshold_medium:
                return "medium"
            else:
                return "low"
        except Exception as e:
            logger.debug("Similarity calculation failed: %s", e)
            return path_relevance

    # Low path: no snippet or semantic disabled
    return path_relevance


async def async_rank_by_similarity(
    items: list[dict[str, Any]],
    target: str,
    *,
    content_key: str = "snippet",
    enable_semantic: bool = True,
    timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Rank items by similarity to target text with async embedding calls.

    Args:
        items: List of dicts with content.
        target: Target text to compare against.
        content_key: Key in dict containing content (default: "snippet").
        enable_semantic: Enable semantic similarity.
        timeout_seconds: Timeout for each embedding call.

    Returns:
        Items sorted by relevance (highest first).
    """
    if not items:
        return items

    scored_items = []
    for item in items:
        content = str(item.get(content_key, "") or "")
        if enable_semantic:
            similarity = await async_semantic_similarity(
                content[:200], target, timeout_seconds=timeout_seconds
            )
        else:
            similarity = 0.0
        scored_items.append((similarity, item))

    # Sort by similarity descending
    scored_items.sort(key=lambda x: x[0], reverse=True)

    return [item for _, item in scored_items]


def warmup_embedding_model() -> bool:
    """Pre-download and cache the embedding model at daemon startup.

    This ensures the model is available in the shared cache before any
    worker processes need it, avoiding repeated downloads or first-use delays.

    Call this at daemon startup to warm up the cache.

    Returns:
        True if model was successfully downloaded/loaded, False otherwise.
    """
    logger.info("Warming up embedding model cache at %s", hf_embedding_cache_dir())

    if not _has_sentence_transformers:
        logger.warning("sentence_transformers not available, skipping warmup")
        return False

    # Try loading the model to trigger download
    model = _get_transformer_model()
    if model is not None:
        logger.info("Embedding model warmup successful: %s", EMBEDDING_MODEL_NAME)
        return True
    else:
        logger.warning("Embedding model warmup failed")
        return False


async def async_warmup_embedding_model() -> bool:
    """Async version of warmup_embedding_model for use in async startup.

    Returns:
        True if model was successfully downloaded/loaded, False otherwise.
    """
    # Run sync warmup in thread pool to avoid blocking
    global _embedding_executor
    if _embedding_executor is None:
        _embedding_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embedding")

    try:
        return await asyncio.get_event_loop().run_in_executor(
            _embedding_executor,
            warmup_embedding_model,
        )
    except Exception as e:
        logger.warning("Async embedding model warmup failed: %s", e)
        return False


# Check availability at import time
def is_semantic_similarity_available() -> bool:
    """Check if semantic similarity is available (sentence_transformers installed and model loadable).

    Returns:
        True if sentence_transformers model is available and loadable.
    """
    return _has_sentence_transformers and _get_transformer_model() is not None
