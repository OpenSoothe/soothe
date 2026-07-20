"""Shim (IG-668): alias ``toolkits/file_ops`` to ``soothe_nano.toolkits.file_ops``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.file_ops")
sys.modules[__name__] = _nano
