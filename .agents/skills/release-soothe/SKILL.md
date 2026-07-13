---
name: release-soothe
description: >-
  Release Soothe packages (soothe, soothe-cli, soothe-daemon, soothe-sdk, soothe-plugins).
  Handles version bumping, changelog maintenance, git tagging, and publishing to PyPI.
  Use when preparing a new release, hotfix, or when the user asks to cut a release.
---

# Release Soothe

Manage Soothe releases: version bumps, changelog updates, git tags, and PyPI publishing.

## When to Use

- User asks to release a new version (`v0.8.0`, `v0.7.17`, etc.)
- User asks to prepare a release notes or update CHANGELOG.md
- User asks to publish packages to PyPI
- User asks how to bump versions or tag a release

## Version Convention

Soothe uses **Semantic Versioning** (semver):

- `MAJOR` (v1.0.0): Breaking changes in public API
- `MINOR` (v0.8.0): New features, backward-compatible
- `PATCH` (v0.7.17): Bug fixes, backward-compatible

Version format: `vMAJOR.MINOR.PATCH` (e.g., `v0.7.16`)

## Changelog Principles

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.

### Section Order

Always maintain this order:

1. `Added` — New features
2. `Changed` — Changes to existing functionality
3. `Deprecated` — Soon-to-be removed features
4. `Removed` — Removed features
5. `Fixed` — Bug fixes
6. `Security` — Security-related changes

### Entry Guidelines

- **Use imperative mood**: `Added` not `Added new feature` or `Adds`
- **Be specific**: `Fixed token tracking in daemon/TUI streams` not `Fixed bugs`
- **Group related changes**: Combine related fixes under one bullet
- **No internal references**: Never expose IG-XXX/RFC-XXX in user-facing text
- **Timestamp format**: `YYYY-MM-DD` (e.g., `2026-07-13`)

### Example Entry

```markdown
## [v0.7.17] - 2026-07-13

### Added
- Skillify embedding resilience with automatic retry and fallback

### Changed
- Pass 1 continuation routing fixes with response-language detection

### Fixed
- Token tracking in daemon/TUI streams
```

## Release Workflow

### 1. Determine Version

Check current version:

```bash
# From VERSION file
cat VERSION

# Or from pyproject.toml
rg '^version = ' packages/soothe/pyproject.toml
```

### 2. Update CHANGELOG.md

Insert new version block at top (below header, above existing entries):

```markdown
## [vX.Y.Z] - YYYY-MM-DD

### Added
- (new features)

### Changed
- (modifications)

### Fixed
- (bug fixes)

[Compare with previous version]: https://github.com/mirasurf/soothe/compare/vX.Y.W...vX.Y.Z
```

### 3. Update Version Files

Synchronize VERSION file and pyproject.toml:

```bash
# Update VERSION
echo "vX.Y.Z" > VERSION

# Update pyproject.toml version
# Edit: version = "X.Y.Z" in each package
```

### 4. Commit Changes

```bash
git add VERSION CHANGELOG.md packages/*/pyproject.toml
git commit -m "Release vX.Y.Z"
```

### 5. Tag Release

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main --tags
```

### 6. Publish to PyPI

```bash
# Build packages
./scripts/build.sh

# Upload (requires PYPI_TOKEN or credentials)
twine upload dist/soothe-*.whl dist/soothe-*.tar.gz
```

Or use the release workflow in `.github/workflows/`.

## Package Inventory

| Package | Directory | Publishes |
|---------|-----------|-----------|
| soothe-core | `packages/soothe/` | PyPI: `soothe` |
| soothe-cli | `packages/soothe-cli/` | PyPI: `soothe-cli` |
| soothe-daemon | `packages/soothe-daemon/` | PyPI: `soothe-daemon` |
| soothe-sdk | `packages/soothe-sdk/` | PyPI: `soothe-sdk` |
| soothe-plugins | `packages/soothe-plugins/` | PyPI: `soothe-plugins` |

## Troubleshooting

- **Version mismatch**: Ensure all `pyproject.toml` files and VERSION are in sync before tagging
- **Changelog merge conflicts**: Preserve existing entries; add new version at top
- **PyPI upload fails**: Verify credentials and check package names match registered names
- **Missing changes**: Search git log since last tag: `git log v0.7.15..HEAD --oneline`

## Quick Reference

| Task | Command |
|------|---------|
| Check current version | `cat VERSION` |
| List recent tags | `git tag -l 'v0.7.*' \| tail -5` |
| View tag details | `git show v0.7.16` |
| Compare versions | `git log v0.7.15..v0.7.16 --oneline` |
| Build packages | `./scripts/build.sh` |
