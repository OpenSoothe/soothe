"""Regression: similarity module must not import sentence_transformers at import time."""

from __future__ import annotations

import sys


def test_similarity_import_does_not_load_sentence_transformers() -> None:
    """Cold import of soothe.utils.similarity should stay lightweight."""
    for mod in (
        "sentence_transformers",
        "transformers",
        "sklearn",
        "soothe.utils.similarity",
    ):
        sys.modules.pop(mod, None)

    import soothe.utils.similarity as sim  # noqa: F401

    assert "sentence_transformers" not in sys.modules
    assert sim._has_sentence_transformers is None
