"""Shim (IG-668): alias ``subagents/deep_research/engine`` to ``soothe_nano.subagents.deep_research.engine``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.engine")
sys.modules[__name__] = _nano
