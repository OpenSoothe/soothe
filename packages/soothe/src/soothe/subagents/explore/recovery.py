"""Shim (IG-668): alias ``subagents/explore/recovery`` to ``soothe_nano.subagents.explore.recovery``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.recovery")
sys.modules[__name__] = _nano
