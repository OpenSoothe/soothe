"""Shim (IG-668): alias ``backends/memory/memu/models`` to ``soothe_nano.backends.memory.memu.models``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.models")
sys.modules[__name__] = _nano
