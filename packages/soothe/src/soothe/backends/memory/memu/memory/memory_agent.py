"""Shim (IG-668): alias ``backends/memory/memu/memory/memory_agent`` to ``soothe_nano.backends.memory.memu.memory.memory_agent``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.memory_agent")
sys.modules[__name__] = _nano
