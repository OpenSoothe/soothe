"""Shim (IG-668): alias ``subagents/explore/prompts`` to ``soothe_nano.subagents.explore.prompts``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.explore.prompts")
sys.modules[__name__] = _nano
