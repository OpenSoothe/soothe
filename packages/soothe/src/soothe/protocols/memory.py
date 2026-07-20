"""Shim (IG-668): alias ``protocols/memory`` to ``soothe_nano.protocols.memory``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.memory")
sys.modules[__name__] = _nano
