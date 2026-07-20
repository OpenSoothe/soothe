"""Shim (IG-668): alias ``subagents/academic_research/persistence`` to ``soothe_nano.subagents.academic_research.persistence``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.academic_research.persistence")
sys.modules[__name__] = _nano
