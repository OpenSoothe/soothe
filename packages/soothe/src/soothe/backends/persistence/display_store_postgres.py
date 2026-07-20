"""Shim (IG-668): alias ``backends/persistence/display_store_postgres`` to ``soothe_nano.backends.persistence.display_store_postgres``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.backends.persistence.display_store_postgres")
sys.modules[__name__] = _nano
