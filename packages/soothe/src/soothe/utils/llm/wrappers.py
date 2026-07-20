"""Shim (IG-668): alias ``utils/llm/wrappers`` to ``soothe_nano.utils.llm.wrappers``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.wrappers")
sys.modules[__name__] = _nano
