"""Shim (IG-668): alias ``subagents/_research_timeouts`` to ``soothe_nano.subagents._research_timeouts``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents._research_timeouts")
sys.modules[__name__] = _nano
