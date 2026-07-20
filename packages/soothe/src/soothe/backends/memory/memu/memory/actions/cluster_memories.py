"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/cluster_memories`` to ``soothe_nano.backends.memory.memu.memory.actions.cluster_memories``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.cluster_memories")
sys.modules[__name__] = _nano
