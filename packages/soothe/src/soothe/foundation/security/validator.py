"""Shim (IG-668): alias to ``soothe_nano.security.validator``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.security.validator")
sys.modules[__name__] = _nano
