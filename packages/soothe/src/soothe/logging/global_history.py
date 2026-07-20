"""Shim (IG-668): alias ``logging/global_history`` to ``soothe_nano.logging.global_history``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.logging.global_history")
sys.modules[__name__] = _nano
