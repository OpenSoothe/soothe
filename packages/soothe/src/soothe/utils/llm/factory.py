"""Shim (IG-668): alias ``utils/llm/factory`` to ``soothe_nano.utils.llm.factory``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.factory")
sys.modules[__name__] = _nano
