"""Shim (IG-668): alias ``subagents/explore/schemas`` to ``soothe_nano.subagents.explore.schemas``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.schemas")
sys.modules[__name__] = _nano
