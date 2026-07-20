"""Shim (IG-668): alias ``skills/registry`` to ``soothe_nano.skills.registry``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.registry")
sys.modules[__name__] = _nano
