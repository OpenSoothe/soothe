"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/get_available_categories`` to ``soothe_nano.backends.memory.memu.memory.actions.get_available_categories``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.get_available_categories")
sys.modules[__name__] = _nano
