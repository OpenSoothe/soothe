"""Shim (IG-668): alias ``subagents/veritas/prompts`` to ``soothe_nano.subagents.veritas.prompts``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.veritas.prompts")
sys.modules[__name__] = _nano
