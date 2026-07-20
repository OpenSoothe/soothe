"""Shim (IG-668): alias ``utils/json_parsing`` to ``soothe_nano.utils.json_parsing``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.json_parsing")
sys.modules[__name__] = _nano
