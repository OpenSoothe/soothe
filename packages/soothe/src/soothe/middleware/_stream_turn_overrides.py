"""Shim (IG-668): alias ``middleware/_stream_turn_overrides`` to ``soothe_nano.middleware._stream_turn_overrides``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware._stream_turn_overrides")
sys.modules[__name__] = _nano
