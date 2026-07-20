"""Shim (IG-668): alias ``backends/memory/memu/config/markdown_config`` to ``soothe_nano.backends.memory.memu.config.markdown_config``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.config.markdown_config")
sys.modules[__name__] = _nano
