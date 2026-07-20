"""Shim (IG-668): alias ``utils/output_capture`` to ``soothe_nano.utils.output_capture``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.output_capture")
sys.modules[__name__] = _nano
