"""Shim (IG-668): alias to ``soothe_nano.skillify.retriever``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skillify.retriever")
sys.modules[__name__] = _nano
