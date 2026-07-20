"""Shim (IG-668): alias ``backends/memory/memu/llm_adapter`` to ``soothe_nano.backends.memory.memu.llm_adapter``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.llm_adapter")
sys.modules[__name__] = _nano
