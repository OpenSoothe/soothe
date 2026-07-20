"""Shim (IG-668): alias ``toolkits/_internal/backend_ops`` to ``soothe_nano.toolkits._internal.backend_ops``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits._internal.backend_ops")
sys.modules[__name__] = _nano
