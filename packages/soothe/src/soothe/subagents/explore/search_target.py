"""Shim (IG-668): alias ``subagents/explore/search_target`` to ``soothe_nano.subagents.explore.search_target``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.search_target")
sys.modules[__name__] = _nano
