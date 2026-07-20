"""Shim (IG-668): alias ``plugin/global_registry`` to ``soothe_nano.plugin.global_registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.global_registry")
sys.modules[__name__] = _nano
