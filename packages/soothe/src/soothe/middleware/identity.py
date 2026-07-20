"""Shim (IG-668): alias ``middleware/identity`` to ``soothe_nano.middleware.identity``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.identity")
sys.modules[__name__] = _nano
