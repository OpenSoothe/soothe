"""LoopRail catalog package (job-scoped autopilot workflow patterns).

Built-in rail YAML lives under ``builtin_rails/``. AutopilotService binds
``LoopRailInterpreter`` on job submit when a ``rail_id`` is resolved.
"""

from soothe.rails.builtins import get_builtin_rails_dir, get_rails_paths
from soothe.rails.catalog import (
    CE_RAIL_BUILTINS,
    LoopRailCatalog,
    RailCatalogError,
    RailDefinition,
    compute_rail_hash,
    load_rail_file,
)
from soothe.rails.selector import resolve_rail_id

__all__ = [
    "CE_RAIL_BUILTINS",
    "LoopRailCatalog",
    "RailCatalogError",
    "RailDefinition",
    "compute_rail_hash",
    "get_builtin_rails_dir",
    "get_rails_paths",
    "load_rail_file",
    "resolve_rail_id",
]
