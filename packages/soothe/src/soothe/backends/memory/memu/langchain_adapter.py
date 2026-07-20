"""Shim (IG-668): alias ``backends/memory/memu/langchain_adapter`` to ``soothe_nano.backends.memory.memu.langchain_adapter``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.langchain_adapter")
sys.modules[__name__] = _nano
