"""Shim (IG-668): alias ``toolkits/_internal/document`` to ``soothe_nano.toolkits._internal.document``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits._internal.document")
sys.modules[__name__] = _nano
