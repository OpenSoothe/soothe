"""Shim (IG-668): alias ``utils/embeddings_dashscope_openai`` to ``soothe_nano.utils.embeddings_dashscope_openai``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.embeddings_dashscope_openai")
sys.modules[__name__] = _nano
