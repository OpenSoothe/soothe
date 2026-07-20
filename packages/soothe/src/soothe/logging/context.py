"""Shim (IG-668): alias ``logging/context`` to ``soothe_nano.logging.context``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.logging.context")
sys.modules[__name__] = _nano
