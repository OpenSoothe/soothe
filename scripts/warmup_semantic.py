#!/usr/bin/env python3
"""Warmup script for semantic similarity model.

Preloads sentence_transformers model to avoid latency on first use.
Run this script during daemon startup or deployment to ensure
the model is ready before explore subagent requests arrive.

Usage:
    # From soothe project root with correct venv activated:
    source .venv/bin/activate
    python scripts/warmup_semantic.py

    # Or directly with correct Python:
    .venv/bin/python scripts/warmup_semantic.py
"""

from __future__ import annotations

import sys
import time

# Ensure we're using the correct venv
if not sys.prefix.endswith("/soothe/.venv"):
    print("⚠ Warning: Not running from soothe/.venv")
    print(f"  Current Python: {sys.prefix}")
    print(f"  Expected: <project>/soothe/.venv")
    print("  Activate correct venv: source .venv/bin/activate")
    print()


def warmup_semantic_model() -> bool:
    """Warmup sentence_transformers model.

    Returns:
        True if warmup successful, False if sentence_transformers unavailable.
    """
    print("Semantic model warmup...")
    start_time = time.perf_counter()

    try:
        # Check if sentence_transformers is available
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("✗ sentence_transformers not installed")
        print("  Install with: pip install sentence-transformers")
        print("  Or use: pip install soothe[semantic]")
        return False

    try:
        # Load the model (same as used in similarity.py)
        model_name = "all-MiniLM-L6-v2"
        print(f"  Loading model: {model_name}")

        model = SentenceTransformer(model_name)

        # Warmup: encode a sample text
        sample_text = "This is a sample text for model warmup"
        embedding = model.encode(sample_text)

        elapsed = time.perf_counter() - start_time
        print(f"✓ Model warmed up in {elapsed:.2f}s")
        print(f"  Model size: ~80MB (all-MiniLM-L6-v2)")
        print(f"  Embedding dimension: {len(embedding)}")

        # Verify model works
        test_similarity = _test_similarity(model)
        if test_similarity:
            print("✓ Similarity calculation verified")

        return True

    except Exception as e:
        print(f"✗ Warmup failed: {e}")
        return False


def _test_similarity(model) -> bool:
    """Test similarity calculation with sample texts."""
    try:
        texts = [
            "Find configuration files in the project",
            "Search for config.yaml and settings.json",
            "Locate all Python source files",
        ]

        embeddings = model.encode(texts)

        # Calculate cosine similarity manually
        from soothe.utils.similarity import cosine_similarity

        sim_01 = cosine_similarity(embeddings[0].tolist(), embeddings[1].tolist())
        sim_02 = cosine_similarity(embeddings[0].tolist(), embeddings[2].tolist())

        print(f"  Test similarity: text1 vs text2 = {sim_01:.3f}")
        print(f"  Test similarity: text1 vs text3 = {sim_02:.3f}")

        # Verify expected behavior: text1 and text2 should be similar
        return sim_01 > 0.5 and sim_02 < sim_01

    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        return False


def main() -> int:
    """Main entry point."""
    success = warmup_semantic_model()

    if success:
        print("\nSemantic similarity is ready for use.")
        print("Explore subagent will use pre-loaded model for relevance scoring.")
        return 0
    else:
        print("\nSemantic similarity unavailable.")
        print("Explore subagent will fallback to keyword matching.")
        return 1


if __name__ == "__main__":
    sys.exit(main())