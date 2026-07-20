"""Shim (IG-668): alias ``plugin/registry`` to ``soothe_nano.plugin.registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.registry")
sys.modules[__name__] = _nano
