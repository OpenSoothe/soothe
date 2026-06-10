"""Regression: similarity module must not import fastembed at import time."""

from __future__ import annotations

import sys


def test_similarity_import_does_not_load_fastembed() -> None:
    """Cold import of soothe.utils.similarity should stay lightweight."""
    for mod in (
        "fastembed",
        "onnxruntime",
        "soothe.utils.similarity",
    ):
        sys.modules.pop(mod, None)

    import soothe.utils.similarity as sim  # noqa: F401

    assert "fastembed" not in sys.modules
    assert sim._has_fastembed is None
