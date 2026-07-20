"""Shim (IG-668): alias to ``soothe_nano.security.policy``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.security.policy")
sys.modules[__name__] = _nano
