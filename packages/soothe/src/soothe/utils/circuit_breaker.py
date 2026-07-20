"""Shim (IG-668): alias ``utils/circuit_breaker`` to ``soothe_nano.utils.circuit_breaker``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.circuit_breaker")
sys.modules[__name__] = _nano
