"""Shim (IG-668): alias to ``soothe_nano.security.operation_security``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.security.operation_security")
sys.modules[__name__] = _nano
