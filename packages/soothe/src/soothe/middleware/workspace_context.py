"""Shim (IG-668): alias ``middleware/workspace_context`` to ``soothe_nano.middleware.workspace_context``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.middleware.workspace_context")
sys.modules[__name__] = _nano
