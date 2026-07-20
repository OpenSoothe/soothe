"""Shim (IG-668): alias ``plugin/cache`` to ``soothe_nano.plugin.cache``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.cache")
sys.modules[__name__] = _nano
