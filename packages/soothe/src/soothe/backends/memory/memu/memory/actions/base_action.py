"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/base_action`` to ``soothe_nano.backends.memory.memu.memory.actions.base_action``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.base_action")
sys.modules[__name__] = _nano
