"""Shim (IG-668): alias ``utils/observability/langfuse/_client`` to ``soothe_nano.utils.observability.langfuse._client``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._client")
sys.modules[__name__] = _nano
