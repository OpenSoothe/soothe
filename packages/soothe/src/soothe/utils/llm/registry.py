"""Shim (IG-668): alias ``utils/llm/registry`` to ``soothe_nano.utils.llm.registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.registry")
sys.modules[__name__] = _nano
