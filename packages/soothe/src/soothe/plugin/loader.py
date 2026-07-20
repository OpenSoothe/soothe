"""Shim (IG-668): alias ``plugin/loader`` to ``soothe_nano.plugin.loader``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.loader")
sys.modules[__name__] = _nano
