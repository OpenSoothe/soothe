"""Shim (IG-668): alias ``middleware/system_prompt`` to ``soothe_nano.middleware.system_prompt``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.system_prompt")
sys.modules[__name__] = _nano
