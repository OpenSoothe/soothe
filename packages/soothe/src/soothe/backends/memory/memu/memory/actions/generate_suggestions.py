"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/generate_suggestions`` to ``soothe_nano.backends.memory.memu.memory.actions.generate_suggestions``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.generate_suggestions")
sys.modules[__name__] = _nano
