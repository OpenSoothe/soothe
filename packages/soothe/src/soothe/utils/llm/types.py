"""Shim (IG-668): alias ``utils/llm/types`` to ``soothe_nano.utils.llm.types``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.types")
sys.modules[__name__] = _nano
