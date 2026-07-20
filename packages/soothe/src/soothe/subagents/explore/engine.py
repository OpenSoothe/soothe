"""Shim (IG-668): alias ``subagents/explore/engine`` to ``soothe_nano.subagents.explore.engine``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.engine")
sys.modules[__name__] = _nano
