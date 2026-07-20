"""Shim (IG-668): alias ``utils/observability/langfuse/_handlers`` to ``soothe_nano.utils.observability.langfuse._handlers``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._handlers")
sys.modules[__name__] = _nano
