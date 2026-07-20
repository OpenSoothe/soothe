"""Shim (IG-668): alias ``backends/durability/base`` to ``soothe_nano.backends.durability.base``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.durability.base")
sys.modules[__name__] = _nano
