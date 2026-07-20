"""Shim (IG-668): alias to ``soothe_nano.filesystem.langchain_adapter``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.filesystem.langchain_adapter")
sys.modules[__name__] = _nano
