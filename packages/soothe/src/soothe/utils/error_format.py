"""Shim (IG-668): alias ``utils/error_format`` to ``soothe_nano.utils.error_format``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.error_format")
sys.modules[__name__] = _nano
