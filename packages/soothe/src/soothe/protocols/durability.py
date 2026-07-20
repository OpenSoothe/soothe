"""Shim (IG-668): alias ``protocols/durability`` to ``soothe_nano.protocols.durability``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.durability")
sys.modules[__name__] = _nano
