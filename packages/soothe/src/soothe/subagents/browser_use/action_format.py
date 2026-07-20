"""Shim (IG-668): alias ``subagents/browser_use/action_format`` to ``soothe_nano.subagents.browser_use.action_format``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use.action_format")
sys.modules[__name__] = _nano
