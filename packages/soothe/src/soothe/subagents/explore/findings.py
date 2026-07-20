"""Shim (IG-668): alias ``subagents/explore/findings`` to ``soothe_nano.subagents.explore.findings``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.findings")
sys.modules[__name__] = _nano
