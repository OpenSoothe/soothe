"""Shim (IG-668): alias ``skills/events`` to ``soothe_nano.skills.events``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.events")
sys.modules[__name__] = _nano
