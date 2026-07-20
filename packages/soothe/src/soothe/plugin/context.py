"""Shim (IG-668): alias ``plugin/context`` to ``soothe_nano.plugin.context``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.context")
sys.modules[__name__] = _nano
