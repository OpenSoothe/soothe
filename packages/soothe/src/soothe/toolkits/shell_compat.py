"""Shim (IG-668): alias ``toolkits/shell_compat`` to ``soothe_nano.toolkits.shell_compat``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.shell_compat")
sys.modules[__name__] = _nano
