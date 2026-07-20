"""Shim (IG-668): alias ``toolkits/progressive/registry`` to ``soothe_nano.toolkits.progressive.registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.progressive.registry")
sys.modules[__name__] = _nano
