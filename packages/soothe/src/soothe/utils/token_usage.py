"""Shim (IG-668): alias ``utils/token_usage`` to ``soothe_nano.utils.token_usage``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.token_usage")
sys.modules[__name__] = _nano
