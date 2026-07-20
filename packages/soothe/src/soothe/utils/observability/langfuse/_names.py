"""Shim (IG-668): alias ``utils/observability/langfuse/_names`` to ``soothe_nano.utils.observability.langfuse._names``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._names")
sys.modules[__name__] = _nano
