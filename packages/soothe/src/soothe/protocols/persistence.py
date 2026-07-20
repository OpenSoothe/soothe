"""Shim (IG-668): alias ``protocols/persistence`` to ``soothe_nano.protocols.persistence``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.persistence")
sys.modules[__name__] = _nano
