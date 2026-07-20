"""Shim (IG-668): alias ``subagents/explore/partial`` to ``soothe_nano.subagents.explore.partial``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.partial")
sys.modules[__name__] = _nano
