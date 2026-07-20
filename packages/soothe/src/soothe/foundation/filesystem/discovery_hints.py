"""Shim (IG-668): alias to ``soothe_nano.filesystem.discovery_hints``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.filesystem.discovery_hints")
sys.modules[__name__] = _nano
