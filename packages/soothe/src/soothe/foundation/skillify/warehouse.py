"""Shim (IG-668): alias to ``soothe_nano.skillify.warehouse``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skillify.warehouse")
sys.modules[__name__] = _nano
