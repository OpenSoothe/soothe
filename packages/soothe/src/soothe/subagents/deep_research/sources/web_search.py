"""Shim (IG-668): alias ``subagents/deep_research/sources/web_search`` to ``soothe_nano.subagents.deep_research.sources.web_search``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.sources.web_search")
sys.modules[__name__] = _nano
