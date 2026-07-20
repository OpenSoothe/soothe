"""Shim (IG-668): alias ``subagents/browser_use/implementation`` to ``soothe_nano.subagents.browser_use.implementation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use.implementation")
sys.modules[__name__] = _nano
