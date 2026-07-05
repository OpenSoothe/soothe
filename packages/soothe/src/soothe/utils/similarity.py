"""Semantic similarity utilities for content scoring.

Provides reusable similarity calculation for:
- Loop message similarity detection (future use)
- Content deduplication and ranking

Uses FastEmbed (ONNX Runtime) when available and cached locally; keyword overlap is
only used inside ``semantic_similarity`` when encoding fails.

Model Cache:
- ``SOOTHE_EMBEDDING_CACHE`` env var overrides cache path (used in Docker builds)
- Default: ``~/.cache/soothe/models/embeddings``
- Use warmup_embedding_model() to pre-download models at daemon startup
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
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
_model_load_thread_lock = threading.Lock()
_model_load_async_lock: asyncio.Lock | None = None
_MODEL_LOAD_TIMEOUT_SECONDS = 30.0

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# FastEmbed is imported lazily on first semantic-similarity use.
_has_fastembed: bool | None = None
_TextEmbedding: type[Any] | None = None
_embedding_model = None
_model_loading_attempted = False


def embedding_cache_dir() -> Path:
    """FastEmbed model cache directory (shared across processes).

    Priority:
    1. ``SOOTHE_EMBEDDING_CACHE`` env var (for Docker builds and custom paths)
    2. Default: ``~/.cache/soothe/models/embeddings``

    Docker builds pre-cache models in ``SOOTHE_EMBEDDING_CACHE`` for faster startup.
    """
    env_cache = os.environ.get("SOOTHE_EMBEDDING_CACHE")
    if env_cache:
        return Path(env_cache)

    return Path.home() / ".cache" / "soothe" / "models" / "embeddings"


def _ensure_fastembed() -> bool:
    """Import FastEmbed on first use (avoids cold import at startup)."""
    global _has_fastembed, _TextEmbedding

    if _has_fastembed is not None:
        return _has_fastembed

    try:
        from fastembed import TextEmbedding

        _TextEmbedding = TextEmbedding
        _has_fastembed = True
        logger.debug("fastembed available, semantic similarity enabled")
    except ImportError:
        _has_fastembed = False
        logger.debug("fastembed not available, falling back to keyword similarity")
    return _has_fastembed


def _ensure_model_load_executor() -> ThreadPoolExecutor:
    global _model_load_executor
    if _model_load_executor is None:
        _model_load_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="fe_model_load",
        )
    return _model_load_executor


def encode_texts(model: Any, texts: list[str]) -> list[list[float]]:
    """Encode texts to embedding vectors using a loaded FastEmbed model.

    Args:
        model: Loaded ``TextEmbedding`` instance.
        texts: Input strings to embed.

    Returns:
        One embedding vector per input text.
    """
    if not texts:
        return []
    embeddings = list(model.embed(texts))
    return [emb.tolist() for emb in embeddings]


def _load_embedding_model_in_thread() -> Any | None:
    """Load the embedding model in a worker thread (may download on first use)."""
    if not _ensure_fastembed() or _TextEmbedding is None:
        return None
    cache_dir = embedding_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    use_offline = is_embedding_model_cached_locally()
    if use_offline:
        logger.debug("Loading embedding model in offline mode (cached locally)")

    try:
        return _TextEmbedding(
            model_name=EMBEDDING_MODEL_NAME,
            cache_dir=str(cache_dir),
            local_files_only=use_offline,
        )
    except OSError as e:
        if use_offline:
            logger.warning("Cached model incomplete, attempting online download: %s", e)
            return _TextEmbedding(
                model_name=EMBEDDING_MODEL_NAME,
                cache_dir=str(cache_dir),
                local_files_only=False,
            )
        raise


def _complete_embedding_model_load(model: Any | None) -> Any | None:
    """Store a loaded model globally and mark the load attempt complete."""
    global _embedding_model, _model_loading_attempted

    _model_loading_attempted = True
    if model is None:
        _embedding_model = None
        return None
    _embedding_model = model
    logger.info(
        "Loaded FastEmbed model: %s (cache: %s)",
        EMBEDDING_MODEL_NAME,
        embedding_cache_dir(),
    )
    return _embedding_model


def get_embedding_model() -> Any | None:
    """Load embedding model synchronously (only when no asyncio loop is running).

    Never call from a running event-loop thread: use ``async_get_embedding_model()``
    instead. Blocking here (including ``Future.result`` during download) stops worker
    heartbeats and triggers pool stuck-worker termination.
    """
    global _embedding_model, _has_fastembed, _model_loading_attempted

    if not _ensure_fastembed():
        return None

    if _model_loading_attempted:
        return _embedding_model

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        logger.warning(
            "get_embedding_model() called on a running event loop; "
            "use async_get_embedding_model() to avoid blocking heartbeats"
        )
        return _embedding_model

    with _model_load_thread_lock:
        if _model_loading_attempted:
            return _embedding_model
        try:
            executor = _ensure_model_load_executor()
            loaded = executor.submit(_load_embedding_model_in_thread).result(
                timeout=_MODEL_LOAD_TIMEOUT_SECONDS,
            )
            return _complete_embedding_model_load(loaded)
        except Exception as e:
            logger.warning("Failed to load FastEmbed model: %s", e)
            _has_fastembed = False
            _model_loading_attempted = True
            _embedding_model = None
            return None


async def async_get_embedding_model() -> Any | None:
    """Load the embedding model without blocking the asyncio event loop."""
    global _embedding_model, _has_fastembed, _model_loading_attempted
    global _model_load_async_lock

    if not _ensure_fastembed():
        return None
    if _embedding_model is not None:
        return _embedding_model
    if _model_loading_attempted:
        return _embedding_model

    if _model_load_async_lock is None:
        _model_load_async_lock = asyncio.Lock()

    async with _model_load_async_lock:
        if _embedding_model is not None:
            return _embedding_model
        if _model_loading_attempted:
            return _embedding_model
        try:
            loop = asyncio.get_running_loop()
            executor = _ensure_model_load_executor()
            loaded = await asyncio.wait_for(
                loop.run_in_executor(executor, _load_embedding_model_in_thread),
                timeout=_MODEL_LOAD_TIMEOUT_SECONDS,
            )
            return _complete_embedding_model_load(loaded)
        except TimeoutError:
            logger.warning(
                "Embedding model load timed out after %.0fs",
                _MODEL_LOAD_TIMEOUT_SECONDS,
            )
            _model_loading_attempted = True
            return None
        except Exception as e:
            logger.warning("Failed to load FastEmbed model: %s", e)
            _has_fastembed = False
            _model_loading_attempted = True
            _embedding_model = None
            return None


def is_embedding_model_cached_locally() -> bool:
    """Return True when ONNX model artifacts exist locally (no download needed).

    Does not load the model or contact the network.
    """
    cache_dir = embedding_cache_dir()
    if not cache_dir.is_dir():
        return False
    return any(path.is_file() for path in cache_dir.rglob("*.onnx"))


def embedding_model_ready_without_download() -> bool:
    """Return True when semantic similarity can run without triggering a model download."""
    if not _ensure_fastembed():
        return False
    if _embedding_model is not None:
        return True
    return is_embedding_model_cached_locally()


def log_skip_semantic_similarity(msg: str, *args: object) -> None:
    """Log that semantic ranking/scoring is skipped and original ordering is kept."""
    reason = msg % args if args else msg
    logger.warning(
        "Skipping semantic similarity (%s); using findings in original order",
        reason,
    )


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

    Uses FastEmbed when available for accurate semantic matching.
    Falls back to keyword overlap when fastembed is not installed.

    WARNING: This function uses synchronous embedding which can block.
    For async contexts, use async_semantic_similarity() which has timeout protection.

    Args:
        text1: First text.
        text2: Second text.
        max_length: Maximum text length for embedding (truncation).

    Returns:
        Similarity score in range [0, 1].
    """
    text1 = (text1 or "").strip()[:max_length]
    text2 = (text2 or "").strip()[:max_length]

    if not text1 or not text2:
        return 0.0

    model = get_embedding_model()
    if model is not None:
        try:
            vectors = encode_texts(model, [text1, text2])
            similarity = cosine_similarity(vectors[0], vectors[1])
            return max(0.0, min(1.0, similarity))
        except Exception as e:
            logger.debug("Embedding similarity failed: %s, falling back to keywords", e)

    return keyword_similarity(text1, text2)


async def async_semantic_similarity(
    text1: str,
    text2: str,
    *,
    max_length: int = 200,
    timeout_seconds: float = _EMBEDDING_TIMEOUT_SECONDS,
) -> float:
    """Calculate semantic similarity with timeout protection for async contexts.

    Wraps the blocking embed call in a thread pool executor with timeout.
    Falls back to keyword similarity on timeout or embedding failure.

    Args:
        text1: First text.
        text2: Second text.
        max_length: Maximum text length for embedding (truncation).
        timeout_seconds: Timeout for embedding call (default: 10s).

    Returns:
        Similarity score in range [0, 1].
    """
    text1 = (text1 or "").strip()[:max_length]
    text2 = (text2 or "").strip()[:max_length]

    if not text1 or not text2:
        return 0.0

    model = await async_get_embedding_model()
    if model is not None:
        try:
            global _embedding_executor
            if _embedding_executor is None:
                _embedding_executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="embedding"
                )

            async with asyncio.timeout(timeout_seconds):
                vectors = await asyncio.get_event_loop().run_in_executor(
                    _embedding_executor,
                    lambda: encode_texts(model, [text1, text2]),
                )
            similarity = cosine_similarity(vectors[0], vectors[1])
            return max(0.0, min(1.0, similarity))
        except TimeoutError:
            logger.warning(
                "Embedding call timed out after %.1fs, falling back to keyword similarity",
                timeout_seconds,
            )
        except Exception as e:
            logger.debug("Embedding similarity failed: %s, falling back to keywords", e)

    return keyword_similarity(text1, text2)


def keyword_similarity(text1: str, text2: str) -> float:
    """Calculate keyword overlap similarity (fallback when embeddings unavailable).

    Args:
        text1: First text.
        text2: Second text.

    Returns:
        Similarity score in range [0, 1].
    """
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union)


def warmup_embedding_model() -> bool:
    """Pre-download and cache the embedding model at daemon startup.

    This ensures the model is available in the shared cache before any
    worker processes need it, avoiding repeated downloads or first-use delays.

    Call this at daemon startup to warm up the cache.

    Returns:
        True if model was successfully downloaded/loaded, False otherwise.
    """
    logger.info("Warming up embedding model cache at %s", embedding_cache_dir())

    if not _ensure_fastembed():
        logger.warning("fastembed not available, skipping warmup")
        return False

    model = get_embedding_model()
    if model is not None:
        logger.info("Embedding model warmup successful: %s", EMBEDDING_MODEL_NAME)
        return True
    logger.warning("Embedding model warmup failed")
    return False


async def async_warmup_embedding_model() -> bool:
    """Async version of warmup_embedding_model for use in async startup.

    Returns:
        True if model was successfully downloaded/loaded, False otherwise.
    """
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


def is_semantic_similarity_available() -> bool:
    """Check if semantic similarity can run without downloading the embedding model.

    Returns:
        True when fastembed is installed and the model is cached or loaded.
    """
    return embedding_model_ready_without_download()
