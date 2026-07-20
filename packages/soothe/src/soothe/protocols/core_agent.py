"""Shim (IG-668): alias ``protocols/core_agent`` to ``soothe_nano.protocols.core_agent``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.core_agent")
sys.modules[__name__] = _nano
