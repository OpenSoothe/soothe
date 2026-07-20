"""Shim (IG-668): alias to ``soothe_nano.filesystem._lock_registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.filesystem._lock_registry")
sys.modules[__name__] = _nano
