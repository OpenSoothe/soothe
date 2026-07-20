"""Shim (IG-668): alias ``middleware/model_call_profiler`` to ``soothe_nano.middleware.model_call_profiler``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.model_call_profiler")
sys.modules[__name__] = _nano
