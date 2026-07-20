"""Shim (IG-668): alias to ``soothe_nano.filesystem.local``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.filesystem.local")
sys.modules[__name__] = _nano
