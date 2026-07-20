"""Shim (IG-668): alias ``backends/durability/sqlite`` to ``soothe_nano.backends.durability.sqlite``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.durability.sqlite")
sys.modules[__name__] = _nano
