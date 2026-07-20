"""Shim (IG-668): alias ``utils/loop_messages`` to ``soothe_nano.utils.loop_messages``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.loop_messages")
sys.modules[__name__] = _nano
