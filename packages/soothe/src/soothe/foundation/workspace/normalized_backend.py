"""Shim (IG-668): alias to ``soothe_nano.workspace.normalized_backend``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.workspace.normalized_backend")
sys.modules[__name__] = _nano
