"""Shim (IG-668): alias ``utils/browser_cdp`` to ``soothe_nano.utils.browser_cdp``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.browser_cdp")
sys.modules[__name__] = _nano
