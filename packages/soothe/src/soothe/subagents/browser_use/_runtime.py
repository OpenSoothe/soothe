"""Shim (IG-668): alias ``subagents/browser_use/_runtime`` to ``soothe_nano.subagents.browser_use._runtime``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use._runtime")
sys.modules[__name__] = _nano
