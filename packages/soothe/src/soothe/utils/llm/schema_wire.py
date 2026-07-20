"""Shim (IG-668): alias ``utils/llm/schema_wire`` to ``soothe_nano.utils.llm.schema_wire``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.utils.llm.schema_wire")
sys.modules[__name__] = _nano
