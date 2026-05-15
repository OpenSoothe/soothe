#!/usr/bin/env python3
"""Standalone embedding model warmup script for Docker builds.

Downloads the sentence_transformers embedding model to a shared cache directory.
Does NOT import soothe code - only requires sentence_transformers package.

Used in Dockerfile.base to pre-cache embedding models before daemon build.

Usage:
    python scripts/warmup_embedding_model.py [--verbose]

Environment:
    HF_HOME: Override HuggingFace cache directory (default: ~/.cache/huggingface)
    SOOTHE_HF_CACHE: Override Soothe-specific cache (default: ~/.cache/soothe/models/huggingface)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def get_cache_dir() -> Path:
    """Get embedding model cache directory.

    Priority:
    1. SOOTHE_HF_CACHE env var (for Docker builds)
    2. Default: ~/.cache/soothe/models/huggingface
    """
    env_cache = os.environ.get("SOOTHE_HF_CACHE")
    if env_cache:
        return Path(env_cache)
    return Path.home() / ".cache" / "soothe" / "models" / "huggingface"


def warmup_model(model_name: str = "all-MiniLM-L6-v2", verbose: bool = False) -> bool:
    """Download and cache the embedding model.

    Args:
        model_name: HuggingFace model name to download.
        verbose: Print progress messages.

    Returns:
        True if successful, False otherwise.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        if verbose:
            print("ERROR: sentence_transformers not installed", file=sys.stderr)
            print("Install with: pip install sentence_transformers", file=sys.stderr)
        return False

    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Warming up embedding model: {model_name}")
        print(f"Cache directory: {cache_dir}")

    try:
        model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
        if verbose:
            print(f"Model loaded successfully: {model_name}")
            print(f"Max sequence length: {model.max_seq_length}")
        return True
    except Exception as e:
        if verbose:
            print(f"ERROR: Failed to load model: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-download embedding model for Soothe daemon",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed progress",
    )
    parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Model name to download (default: all-MiniLM-L6-v2)",
    )
    args = parser.parse_args()

    success = warmup_model(model_name=args.model, verbose=args.verbose)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())