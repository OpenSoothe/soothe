"""Shim (IG-668): alias ``utils/network_errors`` to ``soothe_nano.utils.network_errors``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.network_errors")
sys.modules[__name__] = _nano
