"""Shim (IG-668): alias ``toolkits/progressive/search_tool`` to ``soothe_nano.toolkits.progressive.search_tool``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.progressive.search_tool")
sys.modules[__name__] = _nano
