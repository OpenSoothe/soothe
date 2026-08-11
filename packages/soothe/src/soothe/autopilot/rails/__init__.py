"""LoopRail: job-scoped workflow-pattern catalog + runtime (RFC-231).

This package merges the former split:

- ``soothe.rails``  — static catalog, path tiers, selector, L0 schema,
  verb defaults, and bundled builtin rail YAML.
- ``soothe.autopilot.rails`` — runtime: interpreter, rail exec, guards,
  wave plan, trace store, recipes, worktree ops.

Both now live here as one one-level subpackage under ``soothe.autopilot``
(IG-705). The static/catalog layer (``catalog``, ``builtins``,
``selector``, ``l0_schema``, ``verb_defaults``, ``builtin_rails/``) is the
lower tier; the runtime layer (``interpreter``, ``builtins_exec``,
``guards``, ``wave_plan``, ``recipe_exec``, ``trace_store``, ...) imports
from it, never the reverse.

AutopilotService binds ``LoopRailInterpreter`` on job submit when a
``rail_id`` is resolved (RFC-231 §4, §7).
"""

from __future__ import annotations

# --- runtime layer (was soothe.autopilot.rails) ---
from soothe.autopilot.rails.autoresearch_exec import (
    AUTORESEARCH_RAIL_ID,
    AutoresearchExec,
)

# --- static / catalog layer (was soothe.rails) ---
from soothe.autopilot.rails.builtins import get_builtin_rails_dir, get_rails_paths
from soothe.autopilot.rails.builtins_exec import (
    BuiltinResult,
    GoalAnnotation,
    RailBuiltinExecutor,
    RailJobState,
)
from soothe.autopilot.rails.catalog import (
    BUILTIN_RAIL_IDS,
    CE_RAIL_BUILTINS,
    LoopRailCatalog,
    RailCatalogError,
    RailDefinition,
    compute_rail_hash,
    load_rail_file,
)
from soothe.autopilot.rails.guards import (
    AlwaysMatchGuardEvaluator,
    GuardContext,
    GuardEvaluator,
    LLMGuardEvaluator,
    ScriptedGuardEvaluator,
)
from soothe.autopilot.rails.interpreter import LoopRailInterpreter, RailEvent
from soothe.autopilot.rails.l0_schema import L0_OPS, normalize_do_steps
from soothe.autopilot.rails.recipe_exec import RecipeRunner
from soothe.autopilot.rails.selector import (
    RailAutoPicker,
    RailPickResult,
    resolve_rail_for_job,
    resolve_rail_id,
)
from soothe.autopilot.rails.trace_store import (
    GuardResult,
    JsonlRailTraceStore,
    MemoryRailTraceStore,
    RailTraceStore,
    RuleFireRecord,
    export_trace_evaluation,
)
from soothe.autopilot.rails.verb_defaults import (
    DEFAULT_VERB_BRIEFS,
    DEFAULT_VERB_ROLES,
    DEFAULT_VERB_TAGS,
    interpolate_brief,
    resolve_verb_brief,
)
from soothe.autopilot.rails.wave_plan import (
    WavePlan,
    resolve_fanout_slices,
)

__all__ = [
    "AUTORESEARCH_RAIL_ID",
    "AlwaysMatchGuardEvaluator",
    "AutoresearchExec",
    "BUILTIN_RAIL_IDS",
    "BuiltinResult",
    "CE_RAIL_BUILTINS",
    "DEFAULT_VERB_BRIEFS",
    "DEFAULT_VERB_ROLES",
    "DEFAULT_VERB_TAGS",
    "GoalAnnotation",
    "GuardContext",
    "GuardEvaluator",
    "GuardResult",
    "JsonlRailTraceStore",
    "L0_OPS",
    "LLMGuardEvaluator",
    "LoopRailCatalog",
    "LoopRailInterpreter",
    "MemoryRailTraceStore",
    "RailAutoPicker",
    "RailBuiltinExecutor",
    "RailCatalogError",
    "RailDefinition",
    "RailEvent",
    "RailJobState",
    "RailPickResult",
    "RailTraceStore",
    "RecipeRunner",
    "RuleFireRecord",
    "ScriptedGuardEvaluator",
    "WavePlan",
    "compute_rail_hash",
    "export_trace_evaluation",
    "get_builtin_rails_dir",
    "get_rails_paths",
    "interpolate_brief",
    "load_rail_file",
    "normalize_do_steps",
    "resolve_fanout_slices",
    "resolve_rail_for_job",
    "resolve_rail_id",
    "resolve_verb_brief",
]
