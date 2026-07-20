"""Shim (IG-668): alias to ``soothe_nano.filesystem.workspace``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.filesystem.workspace")
sys.modules[__name__] = _nano
