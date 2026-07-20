"""Shim (IG-668): alias ``logging/thread_logger`` to ``soothe_nano.logging.thread_logger``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.logging.thread_logger")
sys.modules[__name__] = _nano
