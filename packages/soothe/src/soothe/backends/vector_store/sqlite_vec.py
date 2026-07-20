"""Shim (IG-668): alias ``backends/vector_store/sqlite_vec`` to ``soothe_nano.backends.vector_store.sqlite_vec``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.vector_store.sqlite_vec")
sys.modules[__name__] = _nano
