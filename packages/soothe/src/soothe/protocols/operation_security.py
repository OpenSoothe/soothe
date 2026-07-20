"""Shim (IG-668): alias ``protocols/operation_security`` to ``soothe_nano.protocols.operation_security``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.operation_security")
sys.modules[__name__] = _nano
