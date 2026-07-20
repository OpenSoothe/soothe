"""Shim (IG-668): alias ``middleware/code_interpreter`` to ``soothe_nano.middleware.code_interpreter``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.code_interpreter")
sys.modules[__name__] = _nano
