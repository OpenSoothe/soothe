"""Shim (IG-668): alias ``subagents/deep_research/implementation`` to ``soothe_nano.subagents.deep_research.implementation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.implementation")
sys.modules[__name__] = _nano
