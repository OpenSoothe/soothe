"""Shim (IG-668): alias ``subagents/explore/middleware`` to ``soothe_nano.subagents.explore.middleware``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.middleware")
sys.modules[__name__] = _nano
