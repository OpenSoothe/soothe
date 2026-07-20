"""Shim (IG-668): re-export ``soothe_nano.config.env``."""

from soothe_nano.config import env as _env

__all__ = [name for name in dir(_env) if not name.startswith("__")]
globals().update({name: getattr(_env, name) for name in __all__})
