"""Shim (IG-668): alias ``utils/prompt_clock`` to ``soothe_nano.utils.prompt_clock``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.prompt_clock")
sys.modules[__name__] = _nano
