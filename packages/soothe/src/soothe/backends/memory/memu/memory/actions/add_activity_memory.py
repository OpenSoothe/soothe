"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/add_activity_memory`` to ``soothe_nano.backends.memory.memu.memory.actions.add_activity_memory``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.add_activity_memory")
sys.modules[__name__] = _nano
