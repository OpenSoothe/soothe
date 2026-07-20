"""Shim (IG-668): alias ``subagents/research_wire`` to ``soothe_nano.subagents.research_wire``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.research_wire")
sys.modules[__name__] = _nano
