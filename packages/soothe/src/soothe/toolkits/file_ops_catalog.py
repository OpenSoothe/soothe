"""Shim (IG-668): alias ``toolkits/file_ops_catalog`` to ``soothe_nano.toolkits.file_ops_catalog``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.file_ops_catalog")
sys.modules[__name__] = _nano
