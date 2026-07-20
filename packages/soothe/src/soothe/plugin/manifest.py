"""Shim (IG-668): alias ``plugin/manifest`` to ``soothe_nano.plugin.manifest``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.plugin.manifest")
sys.modules[__name__] = _nano
