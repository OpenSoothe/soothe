"""Shim (IG-668): alias ``subagents/deep_research/json_util`` to ``soothe_nano.subagents.deep_research.json_util``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.json_util")
sys.modules[__name__] = _nano
