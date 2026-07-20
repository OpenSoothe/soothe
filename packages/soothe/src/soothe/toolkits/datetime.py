"""Shim (IG-668): alias ``toolkits/datetime`` to ``soothe_nano.toolkits.datetime``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.datetime")
sys.modules[__name__] = _nano
