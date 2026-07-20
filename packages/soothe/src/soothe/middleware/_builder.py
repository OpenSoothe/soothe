"""Shim (IG-668): alias ``middleware/_builder`` to ``soothe_nano.middleware._builder``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware._builder")
sys.modules[__name__] = _nano
