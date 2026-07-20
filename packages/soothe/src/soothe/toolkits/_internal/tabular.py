"""Shim (IG-668): alias ``toolkits/_internal/tabular`` to ``soothe_nano.toolkits._internal.tabular``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits._internal.tabular")
sys.modules[__name__] = _nano
