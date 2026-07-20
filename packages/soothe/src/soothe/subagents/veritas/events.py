"""Shim (IG-668): alias ``subagents/veritas/events`` to ``soothe_nano.subagents.veritas.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.veritas.events")
sys.modules[__name__] = _nano
