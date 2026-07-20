"""Shim (IG-668): alias ``middleware/policy`` to ``soothe_nano.middleware.policy``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.policy")
sys.modules[__name__] = _nano
