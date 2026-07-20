"""Shim (IG-668): alias ``utils/runtime`` to ``soothe_nano.utils.runtime``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.runtime")
sys.modules[__name__] = _nano
