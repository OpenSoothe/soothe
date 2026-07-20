"""Shim (IG-668): alias ``utils/observability/langfuse/_merge`` to ``soothe_nano.utils.observability.langfuse._merge``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._merge")
sys.modules[__name__] = _nano
