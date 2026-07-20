"""Shim (IG-668): alias ``subagents/academic_research/termination`` to ``soothe_nano.subagents.academic_research.termination``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.termination")
sys.modules[__name__] = _nano
