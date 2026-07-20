"""Shim (IG-668): alias ``utils/path`` to ``soothe_nano.utils.path``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.path")
sys.modules[__name__] = _nano
