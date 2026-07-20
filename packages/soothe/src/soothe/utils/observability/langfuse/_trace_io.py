"""Shim (IG-668): alias ``utils/observability/langfuse/_trace_io`` to ``soothe_nano.utils.observability.langfuse._trace_io``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._trace_io")
sys.modules[__name__] = _nano
