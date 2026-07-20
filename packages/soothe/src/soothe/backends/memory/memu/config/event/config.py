"""Shim (IG-668): alias ``backends/memory/memu/config/event/config`` to ``soothe_nano.backends.memory.memu.config.event.config``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.config.event.config")
sys.modules[__name__] = _nano
