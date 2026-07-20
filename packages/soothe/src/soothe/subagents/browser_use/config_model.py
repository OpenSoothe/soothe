"""Shim (IG-668): alias ``subagents/browser_use/config_model`` to ``soothe_nano.subagents.browser_use.config_model``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.browser_use.config_model")
sys.modules[__name__] = _nano
