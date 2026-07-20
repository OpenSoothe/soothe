"""Shim (IG-668): alias ``utils/token_counting`` to ``soothe_nano.utils.token_counting``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.token_counting")
sys.modules[__name__] = _nano
