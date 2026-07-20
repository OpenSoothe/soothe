"""Shim (IG-668): alias ``utils/stream_normalize`` to ``soothe_nano.utils.stream_normalize``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.stream_normalize")
sys.modules[__name__] = _nano
