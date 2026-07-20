"""Shim (IG-668): alias ``backends/vector_store/pgvector`` to ``soothe_nano.backends.vector_store.pgvector``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.vector_store.pgvector")
sys.modules[__name__] = _nano
