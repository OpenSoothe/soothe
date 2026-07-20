"""Shim (IG-668): alias ``middleware/skill_activation`` to ``soothe_nano.middleware.skill_activation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.skill_activation")
sys.modules[__name__] = _nano
