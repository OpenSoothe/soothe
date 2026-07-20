"""Shim (IG-668): alias ``backends/vector_store/weaviate`` to ``soothe_nano.backends.vector_store.weaviate``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.vector_store.weaviate")
sys.modules[__name__] = _nano
