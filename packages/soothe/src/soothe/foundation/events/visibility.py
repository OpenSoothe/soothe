"""Shim (IG-668): alias to ``soothe_nano.events.visibility``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.events.visibility")
sys.modules[__name__] = _nano
