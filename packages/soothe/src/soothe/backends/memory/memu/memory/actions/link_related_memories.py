"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/link_related_memories`` to ``soothe_nano.backends.memory.memu.memory.actions.link_related_memories``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.link_related_memories")
sys.modules[__name__] = _nano
