"""Shim (IG-668): alias ``subagents/plan/schemas`` to ``soothe_nano.subagents.plan.schemas``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.plan.schemas")
sys.modules[__name__] = _nano
