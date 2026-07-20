"""Shim (IG-668): alias ``subagents/browser_use/events`` to ``soothe_nano.subagents.browser_use.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use.events")
sys.modules[__name__] = _nano
