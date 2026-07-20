"""Shim (IG-668): alias ``backends/memory/memu/memory/embeddings`` to ``soothe_nano.backends.memory.memu.memory.embeddings``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.embeddings")
sys.modules[__name__] = _nano
