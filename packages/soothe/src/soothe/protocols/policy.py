"""Shim (IG-668): alias ``protocols/policy`` to ``soothe_nano.protocols.policy``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.policy")
sys.modules[__name__] = _nano
