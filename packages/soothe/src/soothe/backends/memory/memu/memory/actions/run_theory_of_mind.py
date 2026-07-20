"""Shim (IG-668): alias ``backends/memory/memu/memory/actions/run_theory_of_mind`` to ``soothe_nano.backends.memory.memu.memory.actions.run_theory_of_mind``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.memory.memu.memory.actions.run_theory_of_mind")
sys.modules[__name__] = _nano
