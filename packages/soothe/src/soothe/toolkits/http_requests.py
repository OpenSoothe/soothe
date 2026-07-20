"""Shim (IG-668): alias ``toolkits/http_requests`` to ``soothe_nano.toolkits.http_requests``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.http_requests")
sys.modules[__name__] = _nano
