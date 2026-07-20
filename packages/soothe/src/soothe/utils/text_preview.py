"""Shim (IG-668): alias ``utils/text_preview`` to ``soothe_nano.utils.text_preview``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.text_preview")
sys.modules[__name__] = _nano
