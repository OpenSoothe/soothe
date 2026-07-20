"""Shim (IG-668): alias ``skills/corpus_match`` to ``soothe_nano.skills.corpus_match``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.skills.corpus_match")
sys.modules[__name__] = _nano
