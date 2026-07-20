"""Shim (IG-668): alias ``utils/observability/langfuse/tracer`` to ``soothe_nano.utils.observability.langfuse.tracer``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse.tracer")
sys.modules[__name__] = _nano
