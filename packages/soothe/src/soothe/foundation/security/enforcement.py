"""Shim (IG-668): alias to ``soothe_nano.security.enforcement``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.security.enforcement")
sys.modules[__name__] = _nano
