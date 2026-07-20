"""Shim (IG-668): alias ``toolkits/execution`` to ``soothe_nano.toolkits.execution``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.execution")
sys.modules[__name__] = _nano
