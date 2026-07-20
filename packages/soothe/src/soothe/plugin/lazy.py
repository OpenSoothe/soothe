"""Shim (IG-668): alias ``plugin/lazy`` to ``soothe_nano.plugin.lazy``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.lazy")
sys.modules[__name__] = _nano
