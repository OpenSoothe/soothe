"""Shim (IG-668): alias ``subagents/veritas/implementation`` to ``soothe_nano.subagents.veritas.implementation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.veritas.implementation")
sys.modules[__name__] = _nano
