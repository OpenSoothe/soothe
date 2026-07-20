"""Shim (IG-668): alias ``utils/llm/structured`` to ``soothe_nano.utils.llm.structured``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.structured")
sys.modules[__name__] = _nano
