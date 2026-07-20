"""Shim (IG-668): alias ``middleware/_model_override`` to ``soothe_nano.middleware._model_override``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware._model_override")
sys.modules[__name__] = _nano
