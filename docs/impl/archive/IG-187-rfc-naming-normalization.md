# IG-187: RFC Naming Normalization

**Date**: 2026-04-17  
**Status**: In Progress  
**Owner**: Codex

## Objective

Normalize RFC spec filenames to the `RFC-NNN-short-semantic-name.md` pattern and reconcile references so naming is consistent across RFC indexes and cross-links.

## Scope

- `docs/specs/` RFC files that still use bare numeric names.
- Supporting docs that reference renamed RFC paths.

## Plan

1. Inventory RFC files violating the naming pattern.
2. Define short semantic names for each target RFC.
3. Rename files to semantic filenames.
4. Update references in `docs/specs/` and key docs to new paths.
5. Validate no stale links to old bare filenames remain.

## Validation

- No remaining canonical RFC files with bare `RFC-NNN.md` names.
- Index and consolidation docs point to semantic filenames.
- No broken local references to renamed RFC files.
