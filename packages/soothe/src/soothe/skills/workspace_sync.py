"""Shim (IG-668): alias ``skills/workspace_sync`` to ``soothe_nano.skills.workspace_sync``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.workspace_sync")
sys.modules[__name__] = _nano
