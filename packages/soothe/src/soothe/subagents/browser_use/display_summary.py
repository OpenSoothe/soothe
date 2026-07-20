"""Shim (IG-668): alias ``subagents/browser_use/display_summary`` to ``soothe_nano.subagents.browser_use.display_summary``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use.display_summary")
sys.modules[__name__] = _nano
