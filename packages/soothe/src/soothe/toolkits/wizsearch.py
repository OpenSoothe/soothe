"""Shim (IG-668): alias ``toolkits/wizsearch`` to ``soothe_nano.toolkits.wizsearch``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.wizsearch")
sys.modules[__name__] = _nano
