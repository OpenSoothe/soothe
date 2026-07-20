"""Shim (IG-668): alias ``utils/observability/langfuse_system_hint`` to ``soothe_nano.utils.observability.langfuse_system_hint``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse_system_hint")
sys.modules[__name__] = _nano
