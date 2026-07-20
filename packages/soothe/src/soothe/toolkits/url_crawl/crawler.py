"""Shim (IG-668): alias ``toolkits/url_crawl/crawler`` to ``soothe_nano.toolkits.url_crawl.crawler``."""

import sys
from importlib import import_module

_nano = import_module("soothe_nano.toolkits.url_crawl.crawler")
sys.modules[__name__] = _nano
