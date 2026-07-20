"""Shim (IG-668): alias ``backends/memory/memu/memory_store`` to ``soothe_nano.backends.memory.memu.memory_store``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory_store")
sys.modules[__name__] = _nano
