"""Shim (IG-668): alias ``plugin/exceptions`` to ``soothe_nano.plugin.exceptions``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.exceptions")
sys.modules[__name__] = _nano
