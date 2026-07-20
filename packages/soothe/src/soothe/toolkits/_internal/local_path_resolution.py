"""Shim (IG-668): alias ``toolkits/_internal/local_path_resolution`` to ``soothe_nano.toolkits._internal.local_path_resolution``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits._internal.local_path_resolution")
sys.modules[__name__] = _nano
