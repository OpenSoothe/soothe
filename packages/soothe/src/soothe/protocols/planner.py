"""Shim (IG-668): alias ``protocols/planner`` to ``soothe_nano.protocols.planner``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.planner")
sys.modules[__name__] = _nano
