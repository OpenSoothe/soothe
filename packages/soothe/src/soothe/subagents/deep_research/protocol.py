"""Shim (IG-668): alias ``subagents/deep_research/protocol`` to ``soothe_nano.subagents.deep_research.protocol``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.protocol")
sys.modules[__name__] = _nano
