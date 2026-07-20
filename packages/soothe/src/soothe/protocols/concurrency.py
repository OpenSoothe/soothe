"""Shim (IG-668): alias ``protocols/concurrency`` to ``soothe_nano.protocols.concurrency``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.protocols.concurrency")
sys.modules[__name__] = _nano
