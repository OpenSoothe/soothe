"""Host aliases for shared model-catalog helpers.

Thin re-export wrapper — canonical implementation lives in
``soothe_nano.config.models_catalog``.  Do not duplicate or modify
the re-exported symbol here; fix it in nano.
"""

# Re-export facade — canonical source: soothe_nano.config.models_catalog
from soothe_nano.config.models_catalog import build_models_list_payload

__all__ = ["build_models_list_payload"]
