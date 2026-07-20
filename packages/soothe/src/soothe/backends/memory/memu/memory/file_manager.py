"""Shim (IG-668): alias ``backends/memory/memu/memory/file_manager`` to ``soothe_nano.backends.memory.memu.memory.file_manager``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.file_manager")
sys.modules[__name__] = _nano
