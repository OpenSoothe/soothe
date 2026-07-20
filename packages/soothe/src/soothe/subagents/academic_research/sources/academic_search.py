"""Shim (IG-668): alias ``subagents/academic_research/sources/academic_search`` to ``soothe_nano.subagents.academic_research.sources.academic_search``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.sources.academic_search")
sys.modules[__name__] = _nano
