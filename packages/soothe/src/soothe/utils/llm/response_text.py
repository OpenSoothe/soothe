"""Shim (IG-668): alias ``utils/llm/response_text`` to ``soothe_nano.utils.llm.response_text``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.response_text")
sys.modules[__name__] = _nano
