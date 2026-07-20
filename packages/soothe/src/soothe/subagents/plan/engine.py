"""Shim (IG-668): alias ``subagents/plan/engine`` to ``soothe_nano.subagents.plan.engine``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.plan.engine")
sys.modules[__name__] = _nano
