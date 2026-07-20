"""Shim (IG-668): alias ``utils/embeddings_dashscope`` to ``soothe_nano.utils.embeddings_dashscope``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.embeddings_dashscope")
sys.modules[__name__] = _nano
