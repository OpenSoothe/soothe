"""Shim (IG-668): alias ``subagents/academic_research/references`` to ``soothe_nano.subagents.academic_research.references``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.references")
sys.modules[__name__] = _nano
