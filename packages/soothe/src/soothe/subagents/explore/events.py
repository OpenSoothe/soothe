"""Shim (IG-668): alias ``subagents/explore/events`` to ``soothe_nano.subagents.explore.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.events")
sys.modules[__name__] = _nano
