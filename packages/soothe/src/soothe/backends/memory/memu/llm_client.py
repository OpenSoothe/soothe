"""Shim (IG-668): alias ``backends/memory/memu/llm_client`` to ``soothe_nano.backends.memory.memu.llm_client``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.llm_client")
sys.modules[__name__] = _nano
