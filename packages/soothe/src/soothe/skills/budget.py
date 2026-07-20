"""Shim (IG-668): alias ``skills/budget`` to ``soothe_nano.skills.budget``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.budget")
sys.modules[__name__] = _nano
