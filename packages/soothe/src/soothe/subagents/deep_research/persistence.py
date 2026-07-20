"""Shim (IG-668): alias ``subagents/deep_research/persistence`` to ``soothe_nano.subagents.deep_research.persistence``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.persistence")
sys.modules[__name__] = _nano
