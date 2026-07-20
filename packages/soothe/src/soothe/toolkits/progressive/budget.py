"""Shim (IG-668): alias ``toolkits/progressive/budget`` to ``soothe_nano.toolkits.progressive.budget``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.progressive.budget")
sys.modules[__name__] = _nano
