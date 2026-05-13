"""Embedding model cache warmup health check."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from soothe.config import SootheConfig

from soothe_daemon.health.formatters import aggregate_status
from soothe_daemon.health.models import CategoryResult, CheckResult, CheckStatus

_WEIGHT_SUFFIXES = frozenset({".bin", ".safetensors", ".pt", ".pth", ".onnx"})


def _sentence_transformers_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def _embedding_cache_looks_populated(cache_dir: Path) -> bool:
    if not cache_dir.is_dir():
        return False
    for path in cache_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in _WEIGHT_SUFFIXES:
            return True
    return False


async def check_embedding_warmup(config: SootheConfig | None = None) -> CategoryResult:
    """Verify sentence_transformers embedding weights are present on disk.

    Does not load the model. When sentence_transformers is not installed, the
    check is skipped (optional feature).

    Args:
        config: Reserved for parity with other health checks (unused).

    Returns:
        CategoryResult for the ``models`` category.
    """
    del config

    if not _sentence_transformers_available():
        checks = [
            CheckResult(
                name="embedding_model_warmup",
                status=CheckStatus.SKIPPED,
                message="sentence_transformers not installed (semantic similarity optional)",
                details={
                    "remediation": "pip install 'soothe[semantic_similarity]' to enable caching checks",
                },
            )
        ]
        return CategoryResult(
            category="models",
            status=aggregate_status([c.status for c in checks]),
            checks=checks,
        )

    from soothe.utils.similarity import EMBEDDING_MODEL_NAME, hf_embedding_cache_dir

    cache_dir = hf_embedding_cache_dir()
    populated = _embedding_cache_looks_populated(cache_dir)

    if populated:
        checks = [
            CheckResult(
                name="embedding_model_warmup",
                status=CheckStatus.OK,
                message=f"Embedding model cache ready ({EMBEDDING_MODEL_NAME})",
                details={"cache_dir": str(cache_dir), "model": EMBEDDING_MODEL_NAME},
            )
        ]
    else:
        checks = [
            CheckResult(
                name="embedding_model_warmup",
                status=CheckStatus.WARNING,
                message="Embedding model weights not found in cache (first use will download)",
                details={
                    "cache_dir": str(cache_dir),
                    "model": EMBEDDING_MODEL_NAME,
                    "remediation": "Run soothed warmup to pre-download",
                },
            )
        ]

    return CategoryResult(
        category="models",
        status=aggregate_status([c.status for c in checks]),
        checks=checks,
    )
