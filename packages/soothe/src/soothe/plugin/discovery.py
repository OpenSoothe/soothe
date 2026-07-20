"""Shim (IG-668): alias ``plugin/discovery`` to ``soothe_nano.plugin.discovery``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.discovery")
sys.modules[__name__] = _nano
