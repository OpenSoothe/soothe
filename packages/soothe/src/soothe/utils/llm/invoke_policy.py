"""Shim (IG-668): alias ``utils/llm/invoke_policy`` to ``soothe_nano.utils.llm.invoke_policy``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.invoke_policy")
sys.modules[__name__] = _nano
