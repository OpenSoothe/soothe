"""Shim (IG-668): alias ``utils/subagent_emit`` to ``soothe_nano.utils.subagent_emit``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.subagent_emit")
sys.modules[__name__] = _nano
