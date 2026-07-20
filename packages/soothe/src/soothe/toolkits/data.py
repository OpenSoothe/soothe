"""Shim (IG-668): alias ``toolkits/data`` to ``soothe_nano.toolkits.data``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.data")
sys.modules[__name__] = _nano
