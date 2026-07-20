"""Shim (IG-668): alias ``middleware/_utils`` to ``soothe_nano.middleware._utils``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware._utils")
sys.modules[__name__] = _nano
