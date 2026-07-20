"""Shim (IG-668): alias ``skills/catalog`` to ``soothe_nano.skills.catalog``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.catalog")
sys.modules[__name__] = _nano
