"""Shim (IG-668): alias to ``soothe_nano.workspace.context``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.workspace.context")
sys.modules[__name__] = _nano
