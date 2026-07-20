"""Shim (IG-668): alias ``utils/observability/langfuse/_goal_loop`` to ``soothe_nano.utils.observability.langfuse._goal_loop``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.observability.langfuse._goal_loop")
sys.modules[__name__] = _nano
