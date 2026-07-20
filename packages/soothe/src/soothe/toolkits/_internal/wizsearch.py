"""Shim (IG-668): alias ``toolkits/_internal/wizsearch`` to ``soothe_nano.toolkits._internal.wizsearch``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits._internal.wizsearch")
sys.modules[__name__] = _nano
