"""Shim (IG-668): alias ``subagents/explore/tools`` to ``soothe_nano.subagents.explore.tools``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.tools")
sys.modules[__name__] = _nano
