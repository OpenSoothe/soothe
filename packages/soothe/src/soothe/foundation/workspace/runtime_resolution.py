"""Shim (IG-668): alias to ``soothe_nano.workspace.runtime_resolution``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.workspace.runtime_resolution")
sys.modules[__name__] = _nano
