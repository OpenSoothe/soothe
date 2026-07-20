"""Shim (IG-668): alias ``backends/durability/postgresql`` to ``soothe_nano.backends.durability.postgresql``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.durability.postgresql")
sys.modules[__name__] = _nano
