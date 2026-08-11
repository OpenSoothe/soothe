# API Surface & Exported-Type Alignment Rules

> Defines the alignment rules enforced by the RFC↔code boundary checker
> (`scripts/ci_rfc_boundary_check.sh` → `docs/analysis/_build_diff_report.py`,
> TJL-05) over the public API surface and exported types of the three owned
> packages (`soothe`, `soothe-daemon`, `soothe-cli`) and their PyPI leaves
> (`soothe-sdk`, `soothe-nano`, `soothe-deepagents`).
>
> Inputs: TJL-01 RFC schema (`docs/analysis/rfc-module-boundary-schema.json`),
> TJL-02 codebase index (`docs/analysis/tjl-02-codebase-index.json`),
> AGENTS.md §7b DAG, RFC lifecycle states (`docs/specs/templates/rfc-standard.md`).

---

## 1. Purpose & Scope

These rules specify **what "aligned" means** for every RFC-declared API surface
element — entry points, package re-exports, protocol contracts, data models,
and exported symbols — and how the checker classifies each declaration against
the AST-derived module graph.

**In scope:**
- Public API surface: `[project.scripts]` entry points, top-level `__init__.py`
  `__all__` / `__getattr__` re-exports, subpackage `__init__.py` re-exports.
- Contract surface: protocol ABCs and dataclasses declared in
  `soothe_sdk.protocols` (the DAG leaf all owned packages consume).
- Exported symbols: every class/function name an RFC names as an
  "implementation", "channel", "component", "data model", or "contract".

**Out of scope:**
- Internal/private module APIs (prefixed `_`).
- Submodule clients (`client/*`) — consumed as code, not checked.
- Behavioral/runtime correctness (alignment is structural, not behavioral).

---

## 2. Alignment Rule Set

Each rule has: **ID**, **what it checks**, **enforcement mechanism** (the
TJL-05 section that implements it), **pass condition**, and **severity on
failure**.

### R1 — DAG Boundary Integrity

| Field | Value |
|---|---|
| Checks | No owned package imports a package in its `must_not_import` list (AGENTS.md §7b). |
| Mechanism | TJL-05 §1 (`1_dag_boundary_comparison`); cross-package edges from TJL-02 AST graph compared against RFC `may_import`/`must_not_import`. |
| Pass | `forbidden_edges_found` is empty **and** zero source-file violations. Test-only imports to a forbidden package are allowed (dev extra per §7b). |
| Severity on failure | **critical** — any source-file import across a banned boundary is a release blocker. |

### R2 — Declared Path Existence

| Field | Value |
|---|---|
| Checks | Every RFC-declared `module_path` / `module_paths` / `paths` / `channel.path` / `component.path` / `cli` / `tui_registry` / `middleware` path resolves to a file on disk. |
| Mechanism | TJL-05 §2 (`2_declared_path_mismatches`); `check_file_exists()` tries workspace-relative + `packages/<pkg>/src/` normalizations after stripping `:NN` suffixes and parenthetical annotations. |
| Pass | File exists at a resolved candidate path. |
| Severity on failure | **medium** — declared path not found (renamed dir, migrated module, or not-yet-implemented). |

### R3 — API Contract Presence

| Field | Value |
|---|---|
| Checks | Each RFC-declared protocol contract name (e.g. `ContextProtocol`, `PlannerProtocol`) appears in the `exports` list of at least one indexed module. |
| Mechanism | TJL-05 §3 (`3_api_contract_mismatches`); contract name searched across `module_exports` of TJL-02. |
| Pass | Contract name found in ≥1 module's `exports`. |
| Severity on failure | **medium** — DRIFT: contract name not in owned exports (likely migrated to `soothe_sdk` PyPI leaf; see §4 reclassification). |
| Note | A contract found only in `soothe_sdk` (PyPI) is **not a violation** if the RFC has been reclassified to declare the SDK as its home (see R7). |

### R4 — Declared Symbol Implementability

| Field | Value |
|---|---|
| Checks | Each RFC-declared class/function name (from `implementations[]`, `channels[].name`, `channel_components`, `components[].name`) appears in owned-package exports. |
| Mechanism | TJL-05 §4 (`4_declared_but_unimplemented_symbols`); symbol name searched across `all_owned_exports` (union of `soothe`, `soothe-daemon`, `soothe-cli` exports only). |
| Pass | Symbol found in owned exports, OR documented as intentionally deferred (RFC `Status` ≠ `Implemented`). |
| Severity on failure | **high** when RFC `Status: Implemented` but symbol absent (spec lies); **medium** when RFC `Status: Draft`/`Proposed` (speculative, expected). |

### R5 — Data Model Presence

| Field | Value |
|---|---|
| Checks | Each RFC-declared data model name appears in owned-package exports or in `soothe_sdk` exports. |
| Mechanism | TJL-05 §5 (`5_data_model_verification`); model name searched in owned exports first; "NOT FOUND in owned exports (may be in soothe_sdk PyPI)" recorded when absent from owned. |
| Pass | Model found in owned exports **or** in `soothe_sdk` exports (contract leaf is the canonical home for shared data models per RFC-610). |
| Severity on failure | **high** if absent from both owned and SDK; **medium** if absent from owned but present in SDK and RFC not yet updated to reflect migration. |

### R6 — Wire Protocol File Integrity

| Field | Value |
|---|---|
| Checks | RFC-450-declared wire protocol files exist on disk. |
| Mechanism | TJL-05 §7 (`7_wire_protocol_verification`); `declared_files[].path` checked with `check_file_exists()`. |
| Pass | All declared files exist. |
| Severity on failure | **medium** per missing file; **high** if the validation envelope (`protocol/validation.py`) is absent (breaks transport-layer contract). |

### R7 — PyPI Migration Reclassification

| Field | Value |
|---|---|
| Checks | When a contract/data-model/symbol is absent from owned exports but present in `soothe_sdk` or `soothe_nano`, the declaring RFC must be reclassified to name the PyPI package as the canonical home (not the owned `soothe` package). |
| Mechanism | Cross-reference of TJL-05 §3/§4/§5 "NOT FOUND in owned exports" entries against `soothe_sdk`/`soothe_nano` export sets + RFC `Status` field. |
| Pass | RFC declares the PyPI package as the module home, OR RFC `Status` is `Draft`/`Proposed` (migration not yet finalized). |
| Severity on failure | **medium** — documentation drift: RFC still points at `packages/soothe/src/soothe/...` after migration to PyPI. This is the repo's primary drift pattern (see TJL-05 `conclusion.primary_drift_pattern`). |

### R8 — Lifecycle-State Consistency

| Field | Value |
|---|---|
| Checks | An RFC marked `Status: Implemented` must have all its declared symbols/paths/contracts resolvable (R2–R6 pass). |
| Mechanism | Composite: for each RFC with `Status: Implemented`, all TJL-05 findings referencing that RFC must be absent or reclassified (R7). |
| Pass | No high-severity findings against an `Implemented` RFC. |
| Severity on failure | **high** — `Implemented` RFC with unresolved declarations is a spec/code lie; either implement the symbol or downgrade the RFC `Status` to `Proposed`/`Draft`. |

### R9 — Structural Invariant Respect

| Field | Value |
|---|---|
| Checks | AGENTS.md §7b/§10 structural rules (one-way DAG, unified persistence backend, no CLI→daemon import, no daemon→client runtime import) hold in the import graph. |
| Mechanism | TJL-05 §8 (`8_system_invariant_verification`); 17 invariants checked against the codebase import graph. |
| Pass | `dag_violations_count == 0`. |
| Severity on failure | **critical** — invariant breach is a release blocker. |

---

## 3. Severity Classification

The checker consolidates findings into four buckets (TJL-05 §9). Mapping:

| Severity | Trigger | Action |
|---|---|---|
| **critical** | R1 or R9 failure (DAG/invariant breach) | Block release; fix immediately. |
| **high** | R4/R5/R8 failure where RFC `Status: Implemented` | Fix code or downgrade RFC status within the sprint. |
| **medium** | R2/R3/R6/R7 failure (path/contract/migration drift) | Track as docs debt; batch-fix in quarterly RFC audit (RFC-903). |
| **low** | Informational (test-only edges, undeclared-but-compliant edges) | No action; logged for visibility. |

**Zero-critical invariant:** A green CI run requires `critical == []`. High and
medium findings do **not** fail CI (they are tracked debt), except when an
`Implemented` RFC has high-severity unresolved symbols (R8) — those fail CI.

---

## 4. Reclassification & Acceptable Drift

Not every "NOT FOUND" is a violation. The following drift is **acceptable**
and classified medium/low, not high:

1. **PyPI migration** — contract/data-model moved to `soothe_sdk` (per
   RFC-610 module structure refactoring). Acceptable if the RFC is updated to
   name the SDK home (R7). Until updated: medium debt.
2. **Directory rename** — `sloop/`, `cli/` reorganizations leave old paths in
   RFC prose. Acceptable as medium debt until the next RFC audit.
3. **Speculative RFCs** — `Draft`/`Proposed` RFCs naming unimplemented symbols
   are expected; R4 severity is medium, not high.
4. **Test-only edges** — `soothe-daemon → soothe-cli`/`soothe-client` imports
   confined to `tests/` are allowed (AGENTS.md §7b dev extra).

**Unacceptable drift** (fails CI):
- `Implemented` RFC with symbols absent from all packages (R8 high).
- Any source-file import across a `must_not_import` boundary (R1 critical).

---

## 5. Checker Enforcement Points

| Rule | TJL-05 section | Output field | CI gate |
|---|---|---|---|
| R1 | §1 | `forbidden_edges_found` | `len == 0` |
| R2 | §2 | `2_declared_path_mismatches.mismatches` | none (debt) |
| R3 | §3 | `3_api_contract_mismatches.details[status=DRIFT]` | none (debt) |
| R4 | §4 | `4_declared_but_unimplemented_symbols` | high if `Implemented` RFC |
| R5 | §5 | `5_data_model_verification.models_not_found` | high if `Implemented` RFC |
| R6 | §7 | `7_wire_protocol_verification.declared_files[exists=false]` | none (debt) |
| R7 | cross-ref | (derived from §3/§4/§5 + RFC status) | none (debt) |
| R8 | composite | (derived per RFC) | **fails CI** if high |
| R9 | §8 | `8_system_invariant_verification.dag_violations_count` | `== 0` |

---

## 6. Maintenance

- **When adding a new public API symbol**: add it to the owning package's
  subpackage `__init__.py` `__all__` so the TJL-02 indexer captures it; if an
  RFC declares it, ensure the RFC `module_path` matches the actual file.
- **When migrating a contract to `soothe_sdk`**: update the declaring RFC's
  `module_path` to the SDK location and set `Status` appropriately (R7).
- **When renaming a directory**: update all RFC `module_path` declarations in
  the same PR; otherwise R2 records medium debt.
- **Quarterly audit** (RFC-903): sweep all medium findings and reclassify or
  resolve; this is the primary mechanism for closing drift debt.
