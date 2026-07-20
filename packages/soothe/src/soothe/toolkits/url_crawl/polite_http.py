"""Shim (IG-668): alias ``toolkits/url_crawl/polite_http`` to ``soothe_nano.toolkits.url_crawl.polite_http``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.url_crawl.polite_http")
sys.modules[__name__] = _nano
