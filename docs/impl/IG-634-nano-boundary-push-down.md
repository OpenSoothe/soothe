# IG-634: Nano Boundary Push-Down (filesystem → deepagents, skills thin)

**Guide**: IG-634  
**Created**: 2026-07-20  
**Related**: IG-625, AGENTS.md §3/§6, `boundary-fixes.md`, release-soothe skill  
**Status**: In progress — PR-1/2/3 code complete locally; PR-4 release cutover pending publish

### Progress (2026-07-20)

**PR-1 done in `soothe-deepagents` (0.7.23 → 0.7.24):**
- Protocol: `backup_path`, `backup=` kwargs, `BatchedEditOperation`/`BatchedEditResult`, `aedit_batched`
- `FilesystemBackend`: atomic write, backup, locks (`edit_locks` property), version stamps, batched edits
- Public search methods; glob discovery hints in middleware
- Skills: public `parse_skill_metadata` / `list_skills` / `strip_skill_frontmatter`; optional `paths`/`when_to_use`/`core`/`tags`

**PR-2 done in `soothe-nano`:**
- No shim re-exports — callers import deepagents protocol/locks directly
- `LocalFilesystem` write/edit/delete/batch/grep delegate to `FilesystemBackend`
- `grep_search.py` thin façade; line/`apply_diff` remain nano product APIs
- Consumers/tests on deepagents result shapes

**PR-3 done (skills thin):**
- Catalog/index/builtins parse via deepagents public skill APIs
- Progressive registry / budget / corpus_match unchanged; MemU untouched

**Still TODO (PR-4):**
- Coordinated version bumps / changelogs / publish; monorepo pin + `verify_finally.sh` at merge close

---

## Goal

Finish the remaining package-boundary debt in `soothe-nano` that is **not** host
coupling (Part 1 of `boundary-fixes.md` covers daemon/host excision).

Two workstreams:

1. **Filesystem (#4)** — promote general-case FS safety and edit capabilities into
   `soothe-deepagents` (the shared base library), then thin nano to product
   composition (workspace binding, security wiring).
2. **Skills base (#5)** — stop reimplementing deepagents skill discovery/parsers;
   keep nano-only progressive loading / budget / corpus match.

### Explicit non-goals

- **Vendored MemU (`backends/memory/memu/`)** — **keep as-is**. It is a portable
  MemU implementation shipped with nano, not a boundary break and not a
  deepagents duplicate. Do not extract to PyPI or delete under this IG.
- Part 1 host-coupling fixes (#1, #2, #6–#10) — tracked separately in
  `boundary-fixes.md`; assumed done or in parallel.
- Long deprecation / dual-shape shims for old nano FS protocol types — **not
  required** (see Cutover below).

### Design rule (locked)

`soothe-deepagents` is the **general base library** for common coding-agent
scenarios. Capabilities that any deepagents consumer would want (atomic writes,
optional backups, per-path edit serialization, batched edits, shared result
types, glob discovery hints) **belong in deepagents**, not as permanent
“nano extras.” Nano keeps only composition that is product-shaped
(workspace process defaults, nano security policy factory, progressive skills).

### Cutover & version bump (locked)

This IG is a **coordinated cut change** across dependent packages. Do **not**
maintain long dual-API / dual-shape compatibility windows.

- Ship as a **small version upgrade** on all touched libs in one release train
  (illustrative: `soothe-deepagents` + `soothe-nano` + `soothe` + `soothe-daemon`
  + `soothe-cli` + `soothe-plugins` as needed — bump patch or minor per current
  semver of each package).
- Consumers update together (monorepo + published pins). Breaking renames and
  result-type shape convergence are allowed in that cut.
- Changelog each package with a short “Breaking (IG-634 cutover)” note listing
  FS protocol field renames and any removed nano parallel APIs.
- Follow the normal release skill / process at merge close; version numbers are
  chosen at release time, not hard-coded here.

---

## Open decisions (locked in this revision)

| # | Decision | Lock |
|---|---|---|
| D1 | Protocol kwargs for `backup` / batch | Extend `BackendProtocol` signatures with optional kwargs (`backup: bool = False`, etc.) in the cutover. All backends (`State` / `Store` / `Sandbox` / `Composite` / `Filesystem`) updated in the same PR to accept and no-op or implement. |
| D2 | Atomic write default | **Always on** for `FilesystemBackend` write/edit commit paths (temp + `os.replace`). Document same-volume rename constraint; preserve existing `O_NOFOLLOW` / symlink policy. Not applied to State/Store (in-memory). Sandbox: only if the sandbox FS path can honor atomic semantics; otherwise document no-op / best-effort. |
| D3 | Promote scope (v1) | Full atomic / backup / lock / version / batch on **`FilesystemBackend`**. Other backends: accept new protocol kwargs, no-op unless trivial. Sandbox/Composite follow-up only if needed for parity. |
| D4 | Line tools / `apply_diff` | **Keep middleware composition** as the tool surface. Promote shared string/line helpers into `backends/utils.py` only if duplication remains. Do **not** grow `BackendProtocol` with `edit_lines` / `apply_diff` in v1. |
| D5 | `UnifiedFilesystem` fate | Keep as a **thin nano façade** over deepagents-backed local FS for workspace/security composition. Delete abstract methods that merely duplicate `BackendProtocol`; collapse unused surface in the cut. |
| D6 | Dual-shape nano types | **No shim.** Nano re-exports deepagents types; update all nano/host consumers and tests in the cutover PR train. |

---

## Workstream A — Filesystem promote + thin (#4)

### A0. Capability classification (locked)

| Capability | Disposition |
|---|---|
| Core CRUD / glob / grep / `virtual_mode` | **Converge** on `soothe_deepagents.backends.FilesystemBackend` |
| Protocol result types | **Single source** in deepagents; nano re-exports (cutover — see A0.5) |
| Atomic write (`temp` + `os.replace`) | **Promote** into deepagents `FilesystemBackend` (always-on, D2) |
| Optional backup on write/edit/delete + `backup_path` | **Promote** into deepagents protocol + `FilesystemBackend` |
| Per-path edit locks | **Promote** into deepagents util; middleware `_active_edit_paths_lock` stays as same-turn tool guard |
| Optimistic version stamp on RMW | **Promote** into deepagents edit/write commit paths |
| `BatchedEdit*` / `aedit_batched` | **Promote** into deepagents protocol + `FilesystemBackend` |
| Line tools / `apply_diff` | Middleware-only (D4); shared helpers in utils if needed |
| Glob discovery hints | **Promote** into deepagents middleware tool descriptions / helpers |
| Grep search | **Public** deepagents search API + nano thin delegate (A5) |
| LangChain / tool factory | Delegate to `FilesystemMiddleware` factories where possible |
| `WorkspaceFilesystem` + process workspace | **Keep in nano** |
| Security / path-validation factory | **Keep in nano** (thin adapter) |
| `SOOTHE_FS_*` / `SOOTHE_RG_PATH` | Generic names in deepagents; nano may alias |

### A0.5. Type convergence map (cutover — required before A3)

Nano and deepagents shapes differ today. **Target = deepagents shapes**, extended
only where the field is common-case. Update all callers in the cut; no dual façade.

| Type | Today (nano) | Today (deepagents) | Cutover target |
|---|---|---|---|
| `ReadResult` | `content`, `is_binary`, … | `error`, `file_data: FileData` | deepagents; callers use `file_data` |
| `WriteResult` | `path`, `bytes_written`, `created`, `backup_path` | `error`, `path`, `files_update` | deepagents + optional `backup_path`; drop nano-only `bytes_written`/`created` unless promoted as common-case (prefer drop) |
| `EditResult` | `old_hash`/`new_hash`, `lines_changed`, `backup_path` | `error`, `path`, `occurrences` | deepagents + optional `backup_path`; version stamp stays internal (not hash fields on result) |
| `DeleteResult` | + `backup_path` | `error`, `path` | deepagents + optional `backup_path` |
| `GrepMatch` | `line_number`, `line_content`, span fields | `path`, `line`, `text` | deepagents names; drop span unless promoted |
| `FileInfo` | frozen dataclass (+ permissions/mime) | minimal `TypedDict` | deepagents `TypedDict`; optional extra keys only if common-case |
| `GlobResult.matches` | `list[str]` | `list[FileInfo]` | deepagents (`list[FileInfo]`); update glob consumers |
| Batch types | nano-local | absent | **Add** to deepagents protocol |

**Consumer blast radius (must update in cut):** nano `filesystem/*`,
`middleware/edit_coalescing.py`, workspace FS tests, `packages/soothe/examples/filesystem_example.py`,
`langchain_adapter_example.py`, and any host imports of nano protocol fields.

### A1. Extend deepagents protocol for promoted fields

- **Edit** `packages/soothe-deepagents/soothe_deepagents/backends/protocol.py`
- **Add / extend**:
  - optional `backup_path: str | None = None` on `WriteResult` / `EditResult` / `DeleteResult`
  - `BatchedEditOperation`, `BatchedEditResult`
  - optional kwargs on `write` / `edit` / `delete` / async variants: at least
    `backup: bool = False` (D1); batch method(s) on protocol or filesystem-only
    with protocol documentation
- **Edit** every backend implementing `BackendProtocol` in the same PR so
  signatures match (no-op `backup` where inapplicable).
- **Add** unit tests for new fields and no-op behavior on non-FS backends.

### A2. Promote atomic write, backup, locks, versioned RMW, batched edit

- **Edit** `packages/soothe-deepagents/soothe_deepagents/backends/filesystem.py`
- **Port from** `soothe_nano.filesystem.local` (behavior-preserving strength):
  - `_write_atomic` (temp file + `os.replace`; same-volume constraint documented)
  - `_create_backup` / `backup_dir`
  - per-path lock registry (sync + async)
  - mtime+size version-stamp check before commit on edit/write paths
  - `aedit_batched` / batched apply with overlap detection
- **Add** `packages/soothe-deepagents/soothe_deepagents/backends/_edit_locks.py`
  (or `edit_locks.py` if exported) for reuse.
- **Edit** `packages/soothe-deepagents/soothe_deepagents/middleware/filesystem.py`
  - optional `backup` on write/edit tools (delete already has it)
  - adopt discovery-hint strings for glob tool description / timeout errors
- **Add** deepagents unit tests ported from nano atomic/backup/lock/batch coverage
  (**do not weaken** assertions — AGENTS.md §8).

### A2b. Publicize search helpers (required for A5)

- **Edit** `packages/soothe-deepagents/soothe_deepagents/backends/filesystem.py`
  and/or `backends/utils.py`
- **Expose** a stable public API for ripgrep + Python fallback search (today
  `_ripgrep_search` / `_python_search` are private instance methods).
- Suggested shape: module-level functions or methods documented in
  `backends/__init__.py` / `__all__` so nano does not import `_`-prefixed APIs.
- **Add** unit tests for the public entry points.

### A3. Collapse nano protocol to re-exports (cutover)

- **Edit** `packages/soothe-nano/src/soothe_nano/filesystem/protocol.py`
- **Replace** local type definitions with re-exports from
  `soothe_deepagents.backends.protocol` (post A0.5 / A1).
- **Update all consumers** to deepagents field names in the same PR slice
  (D6 — no dual-shape shim).
- **Remove** nano `.to_dict()` helpers if unused after cut; prefer deepagents
  shapes / plain dataclasses.

### A4. Thin `LocalFilesystem` + `UnifiedFilesystem`

- **Edit** `packages/soothe-nano/src/soothe_nano/filesystem/local.py`
  - wrap/subclass `FilesystemBackend` for core ops; delete duplicated
    atomic/backup/lock/batch bodies once A2 is green.
- **Edit** `packages/soothe-nano/src/soothe_nano/filesystem/unified.py`
  - thin façade (D5); drop abstract surface that only mirrors `BackendProtocol`.
- Fold workspace-only path helpers into `WorkspaceFilesystem` where possible.
- **Remove** dead helpers after delegation.

### A5. Delegate grep + LangChain adapter; drop parallel stacks

- **Edit** `packages/soothe-nano/src/soothe_nano/filesystem/grep_search.py`
  - call **public** deepagents search API (A2b); keep `SOOTHE_RG_PATH` alias if needed.
- **Edit** `packages/soothe-nano/src/soothe_nano/filesystem/langchain_adapter.py`
  - prefer `FilesystemMiddleware` tool factories; retain only nano-specific surface.
- **Remove** superseded private search/tool helpers once unused.

### A6. Product composition + consumer cutover

- **Keep** `WorkspaceFilesystem`, `factory.py` security wiring, process workspace
  resolution in nano — retarget to deepagents-backed local FS.
- **Update** `middleware/edit_coalescing.py` for new batch/result types.
- **Update** `packages/soothe/examples/filesystem_example.py` and
  `langchain_adapter_example.py` for cutover types/APIs.
- **Audit** `tests/unit/core/filesystem/` + `tests/unit/middleware/test_edit_coalescing*.py`:
  - move pure engine tests (atomic/lock/batch) into deepagents where behavior now lives
  - keep nano tests for workspace/security composition and integration

### A7. Verification (filesystem)

```bash
# from packages/soothe-deepagents
pytest tests/unit_tests/ -k 'filesystem or backend or middleware or edit_lock or grep' -q

# from packages/soothe-nano
pytest tests/unit/core/filesystem/ tests/unit/middleware/test_edit_coalescing*.py -q
```

---

## Workstream B — Skills base thin (#5)

### B0. Classification

| Piece | Disposition |
|---|---|
| Frontmatter / `SkillMetadata` / list skills from dirs | **Delegate** to deepagents; **publicize** parsers (B1b) |
| `SkillIndex` stat invalidation | **Wrap** deepagents listing; keep nano JSON cache only if still needed |
| Builtin skill *name list* | **Keep in nano** |
| `ProgressiveSkillRegistry`, `corpus_match`, `budget`, `discovery_tools` | **Keep in nano** (product) |
| Nano `SkillIndexEntry` fields (`paths`, `when_to_use`, `core`) | Map onto `SkillMetadata` / `metadata`; **promote** first-class fields if common-case |

### B1. Confirm parity

- **Read** deepagents `SkillMetadata` / `_parse_skill_metadata` / `_list_skills`
  vs nano `skills/catalog.py` / `skills/index.py`.
- Any frontmatter field nano needs that deepagents lacks → **promote into
  deepagents** (same common-case rule), do not fork parsers.

### B1b. Publicize skill parse/list APIs

- **Edit** `packages/soothe-deepagents/soothe_deepagents/middleware/skills.py`
- Export stable public helpers (e.g. `parse_skill_metadata`, `list_skills`) via
  `__all__` / package exports so nano does not depend on `_`-prefixed functions.
- Cutover: nano imports the public API only.

### B2. Delegate parsers

- **Edit** `packages/soothe-nano/src/soothe_nano/skills/catalog.py`
- Replace `_parse_frontmatter` / `_parse_skill_directory` / `read_skill_markdown`
  bodies with deepagents public APIs.
- Keep `build_skill_context_text` only if it adds nano-specific formatting.

### B3. Thin SkillIndex

- **Edit** `packages/soothe-nano/src/soothe_nano/skills/index.py`
- Wrap deepagents discovery/invalidation; retain
  `~/.soothe/cache/skill_index.json` only if still needed after cut.

### B4. Builtins

- **Edit** `packages/soothe-nano/src/soothe_nano/skills/builtins.py`
- Delegate path discovery to deepagents source-loading; keep builtin names in nano.

### B5. Verification (skills)

```bash
pytest tests/unit/core/skills/ tests/unit/middleware/test_skill_discovery_middleware.py -q
```

---

## Workstream C — Verification, release cutover & enforcement

- Run `scripts/check_module_import_boundaries.sh` (Rule 3b/3c).
- Run `./scripts/verify_finally.sh` after each merged phase (or at IG close).
- Confirm MemU tree untouched:
  `git diff --stat -- packages/soothe-nano/src/soothe_nano/backends/memory/memu`
  → empty for this IG.
- Cleanse dead nano FS/skills helpers after promote (AGENTS.md §6).
- **Release cutover**: bump small versions on all affected packages; update
  inter-package pins; changelog “Breaking (IG-634 cutover)” sections; publish
  per release-soothe skill when approving the train.

---

## Risks

| Risk | Mitigation |
|---|---|
| Result-type field renames break callers | A0.5 map + full consumer/test update in cut; no shim |
| Protocol signature change breaks third-party backends | Same-train update of all in-tree backends; document in deepagents changelog |
| Atomic `os.replace` across devices | Keep temp file on same directory as target; document constraint |
| Weakening nano FS tests when moving | Port assertions into deepagents; keep composition tests in nano |
| Private API leakage (`_ripgrep_*`, `_parse_skill_*`) | A2b + B1b public exports before nano delegates |

---

## Success metrics

- Deepagents owns atomic/backup/lock/version/batch + public search/skill-parse APIs.
- Nano `filesystem/` parallel engine LOC substantially reduced (target: protocol
  re-export + thin local/workspace/factory only; grep/langchain are shims).
- Zero remaining nano definitions of shared FS result types.
- Skills parsers call public deepagents APIs; progressive stack unchanged.
- MemU diff empty; boundary script + `verify_finally.sh` green.
- Coordinated small version bumps published for affected libs.

---

## Suggested PR slices

1. **PR-1 (deepagents FS promote + public search)**: A1 + A2 + A2b + deepagents tests.
2. **PR-2 (nano FS thin + type cutover)**: A0.5 consumer updates + A3–A6 + examples + nano tests moved/updated.
3. **PR-3 (skills publicize + thin)**: B1 + B1b + B2–B4 + skills tests.
4. **PR-4 (enforcement + version cutover)**: C + dead-code cleanse + version bumps / changelogs / pins.

---

## Exit criteria

- Common FS safety/edit features live in `soothe-deepagents` with deepagents tests.
- Nano `filesystem/` is composition-only (workspace/security); no parallel engine.
- Nano skills parsers use public deepagents APIs; progressive registry remains.
- Vendored MemU unchanged.
- Boundary script + `verify_finally.sh` green.
- Small version upgrade cut shipped across affected packages.

---

## Task matrix

| ID | Workstream | Scope | Risk | Done criteria |
|----|------------|-------|------|---------------|
| T1 | A1 / D1 | Protocol extensions + all backends signature update | High | Types + kwargs land; in-tree backends compile/test |
| T2 | A2 / D2–D3 | Atomic / backup / locks / version / batch on `FilesystemBackend` | High | Nano-strength tests in deepagents |
| T3 | A2 | Discovery hints + middleware write/edit `backup` | Medium | Tool UX parity |
| T4 | A2b | Public search API | Medium | Nano can delegate without `_` imports |
| T5 | A0.5 + A3 / D6 | Type cutover + nano re-exports + consumer updates | High | No dual shapes; callers use deepagents fields |
| T6 | A4 / D5 | Thin `LocalFilesystem` + `UnifiedFilesystem` | High | Parallel engine bodies gone |
| T7 | A5 | Grep + LangChain delegate | Medium | Parallel stacks deleted or thin aliases |
| T8 | A6 | Workspace / factory / edit_coalescing / examples | Medium | Composition + examples on new types |
| T9 | B1 + B1b | Skills parity + publicize parsers | Medium | Public deepagents skill parse/list API |
| T10 | B2–B4 | Catalog / SkillIndex / builtins thin | Low | Progressive stack unchanged |
| T11 | C | Boundary + verify + MemU untouched + version cutover | Medium | Scripts green; pins bumped; changelogs note breaking cut |

---

## Priority order

1. T1–T4 (base lib + public APIs first).
2. T5–T8 (nano FS cutover).
3. T9–T10 (skills).
4. T11 (enforcement + coordinated version bump).
