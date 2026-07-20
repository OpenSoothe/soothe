"""Shim (IG-668): alias ``subagents/deep_research/report_classifier`` to ``soothe_nano.subagents.deep_research.report_classifier``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.subagents.deep_research.report_classifier")
sys.modules[__name__] = _nano
