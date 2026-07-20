"""Shim (IG-668): alias ``skills/search`` to ``soothe_nano.skills.search``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.search")
sys.modules[__name__] = _nano
