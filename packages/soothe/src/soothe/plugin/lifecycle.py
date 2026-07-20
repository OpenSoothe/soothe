"""Shim (IG-668): alias ``plugin/lifecycle`` to ``soothe_nano.plugin.lifecycle``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.lifecycle")
sys.modules[__name__] = _nano
