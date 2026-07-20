"""Shim (IG-668): alias ``subagents/academic_research/display_summary`` to ``soothe_nano.subagents.academic_research.display_summary``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.display_summary")
sys.modules[__name__] = _nano
