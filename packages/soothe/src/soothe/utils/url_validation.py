"""Shim (IG-668): alias ``utils/url_validation`` to ``soothe_nano.utils.url_validation``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.url_validation")
sys.modules[__name__] = _nano
