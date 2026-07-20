"""Shim (IG-668): alias ``middleware/role_routing`` to ``soothe_nano.middleware.role_routing``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.role_routing")
sys.modules[__name__] = _nano
