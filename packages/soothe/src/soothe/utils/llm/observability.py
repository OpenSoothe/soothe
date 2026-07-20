"""Shim (IG-668): alias ``utils/llm/observability`` to ``soothe_nano.utils.llm.observability``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.observability")
sys.modules[__name__] = _nano
