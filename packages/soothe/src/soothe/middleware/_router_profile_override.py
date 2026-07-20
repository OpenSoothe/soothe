"""Shim (IG-668): alias ``middleware/_router_profile_override`` to ``soothe_nano.middleware._router_profile_override``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware._router_profile_override")
sys.modules[__name__] = _nano
