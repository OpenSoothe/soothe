"""Shim (IG-668): alias ``protocols/vector_store`` to ``soothe_nano.protocols.vector_store``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.vector_store")
sys.modules[__name__] = _nano
