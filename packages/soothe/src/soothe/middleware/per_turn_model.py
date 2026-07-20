"""Shim (IG-668): alias ``middleware/per_turn_model`` to ``soothe_nano.middleware.per_turn_model``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.per_turn_model")
sys.modules[__name__] = _nano
