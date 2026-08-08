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
from soothe.rails.l0_schema import L0_OPS, normalize_do_steps
from soothe.rails.selector import (
    RailAutoPicker,
    RailPickResult,
    resolve_rail_for_job,
    resolve_rail_id,
)
from soothe.rails.verb_defaults import (
    DEFAULT_VERB_BRIEFS,
    interpolate_brief,
    resolve_verb_brief,
)

__all__ = [
    "CE_RAIL_BUILTINS",
    "DEFAULT_VERB_BRIEFS",
    "L0_OPS",
    "LoopRailCatalog",
    "RailAutoPicker",
    "RailCatalogError",
    "RailDefinition",
    "RailPickResult",
    "compute_rail_hash",
    "get_builtin_rails_dir",
    "get_rails_paths",
    "interpolate_brief",
    "load_rail_file",
    "normalize_do_steps",
    "resolve_rail_for_job",
    "resolve_rail_id",
    "resolve_verb_brief",
]
