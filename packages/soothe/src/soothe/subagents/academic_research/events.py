"""Shim (IG-668): alias ``subagents/academic_research/events`` to ``soothe_nano.subagents.academic_research.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.events")
sys.modules[__name__] = _nano
