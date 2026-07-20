"""Shim (IG-668): alias ``skills/index`` to ``soothe_nano.skills.index``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.index")
sys.modules[__name__] = _nano
