"""Shim (IG-668): alias ``subagents/_research_json_util`` to ``soothe_nano.subagents._research_json_util``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents._research_json_util")
sys.modules[__name__] = _nano
