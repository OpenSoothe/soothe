"""Shim (IG-668): alias ``skills/builtins`` to ``soothe_nano.skills.builtins``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.builtins")
sys.modules[__name__] = _nano
