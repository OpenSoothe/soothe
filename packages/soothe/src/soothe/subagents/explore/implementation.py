"""Shim (IG-668): alias ``subagents/explore/implementation`` to ``soothe_nano.subagents.explore.implementation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.implementation")
sys.modules[__name__] = _nano
