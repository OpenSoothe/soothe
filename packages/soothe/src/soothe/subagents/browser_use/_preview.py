"""Shim (IG-668): alias ``subagents/browser_use/_preview`` to ``soothe_nano.subagents.browser_use._preview``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use._preview")
sys.modules[__name__] = _nano
