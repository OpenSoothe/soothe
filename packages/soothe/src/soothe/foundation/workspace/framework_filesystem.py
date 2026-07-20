"""Shim (IG-668): alias to ``soothe_nano.workspace.framework_filesystem``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.workspace.framework_filesystem")
sys.modules[__name__] = _nano
