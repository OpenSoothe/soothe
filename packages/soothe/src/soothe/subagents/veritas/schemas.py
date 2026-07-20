"""Shim (IG-668): alias ``subagents/veritas/schemas`` to ``soothe_nano.subagents.veritas.schemas``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.veritas.schemas")
sys.modules[__name__] = _nano
