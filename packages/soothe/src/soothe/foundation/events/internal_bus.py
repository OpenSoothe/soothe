"""Shim (IG-668): alias to ``soothe_nano.events.internal_bus``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.events.internal_bus")
sys.modules[__name__] = _nano
