"""Shim (IG-668): alias ``toolkits/deepxiv`` to ``soothe_nano.toolkits.deepxiv``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.deepxiv")
sys.modules[__name__] = _nano
