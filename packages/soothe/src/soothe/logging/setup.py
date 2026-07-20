"""Shim (IG-668): alias ``logging/setup`` to ``soothe_nano.logging.setup``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.logging.setup")
sys.modules[__name__] = _nano
