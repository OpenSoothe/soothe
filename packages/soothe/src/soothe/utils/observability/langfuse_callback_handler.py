"""Shim (IG-668): alias ``utils/observability/langfuse_callback_handler`` to ``soothe_nano.utils.observability.langfuse_callback_handler``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse_callback_handler")
sys.modules[__name__] = _nano
