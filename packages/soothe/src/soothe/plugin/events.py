"""Shim (IG-668): alias ``plugin/events`` to ``soothe_nano.plugin.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.events")
sys.modules[__name__] = _nano
