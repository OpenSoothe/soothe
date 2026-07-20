"""Shim (IG-668): alias ``subagents/explore/normalize`` to ``soothe_nano.subagents.explore.normalize``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.normalize")
sys.modules[__name__] = _nano
