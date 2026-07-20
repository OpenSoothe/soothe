"""Shim (IG-668): alias ``utils/thread_id`` to ``soothe_nano.utils.thread_id``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.thread_id")
sys.modules[__name__] = _nano
