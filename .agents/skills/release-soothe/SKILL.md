---
name: release-soothe
description: >-
  Release Soothe packages (soothe, soothe-cli, soothe-daemon) and language
  clients (Python, TypeScript, Go, Rust). soothe-sdk and soothe-nano
  publish from their own repos (mirasoth/soothe-sdk,
  mirasoth/soothe-nano), not this monorepo. Handles
  version bumping, changelog maintenance, git tagging, publishing (PyPI / npm /
  crates.io / Go modules), and monorepo submodule bumps.
  Use when preparing a new release, hotfix, client SDK release, or when the
  user asks to cut a release.
---

# Release Soothe

Manage Soothe releases: version bumps, changelog updates, git tags, registry
publishing, and language-client releases (separate repos under `client/`).

## When to Use

- User asks to release a new version (`v0.8.0`, `v0.7.17`, etc.)
- User asks to prepare release notes or update CHANGELOG.md
- User asks to publish packages to PyPI / npm / crates.io
- User asks to release a language client (`soothe-client-python`, Go, TS, Rust)
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

---

## Monorepo Core Release Workflow

### 1. Determine Version

```bash
# Monorepo release version (soothe / soothe-cli / soothe-daemon)
cat VERSION

# Standalone package versions (independent of root VERSION; publish from own repos)
rg '^version = ' packages/soothe-sdk/pyproject.toml
rg '^version = ' packages/soothe-nano/pyproject.toml
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

[Compare with previous version]: https://github.com/mirasoth/soothe/compare/vX.Y.W...vX.Y.Z
```

### 3. Update Version Files

Synchronize the monorepo `VERSION` for core packages. **soothe-sdk** and
**soothe-nano** version bumps and PyPI publishes happen in their own repos
([mirasoth/soothe-sdk](https://github.com/mirasoth/soothe-sdk),
[mirasoth/soothe-nano](https://github.com/mirasoth/soothe-nano)); this
monorepo only pins those submodules and waits for the versions on PyPI when
needed.

When bumping `soothe-nano` / `soothe-sdk` floors in `packages/soothe/pyproject.toml`,
**also update the matching `soothe-sdk` pin in `packages/soothe-daemon/pyproject.toml`**
(daemon does not re-pin `soothe-nano`; it comes via `soothe`). Keep daemon's
`soothe>=…` floor admitting monorepo `VERSION`. The Docker image co-installs
`soothe==V` and `soothe-daemon==V`; disjoint sdk ranges or a `soothe` pin that
misses `VERSION` (caught by `scripts/check_first_party_pin_alignment.py`) make
the image build unsatisfiable.

```bash
# Update monorepo VERSION (soothe / soothe-cli / soothe-daemon)
echo "X.Y.Z" > VERSION

# For soothe-sdk / soothe-nano: release in the package repo,
# then bump the submodule pin here.
# Keep soothe + soothe-daemon first-party pins aligned (soothe floor + sdk).
uv run python scripts/check_first_party_pin_alignment.py
```

### 4. Commit, Tag, Publish

```bash
git add VERSION CHANGELOG.md packages/*/pyproject.toml
git commit -m "Release vX.Y.Z"
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin main --tags
./scripts/build.sh
twine upload dist/soothe-*.whl dist/soothe-*.tar.gz
```

Or use the release workflow in `.github/workflows/`.

### Package Inventory (monorepo)

| Package | Directory | Version source | Publishes |
|---------|-----------|----------------|-----------|
| soothe-core | `packages/soothe/` | Root `VERSION` | PyPI: `soothe` |
| soothe-cli | `packages/soothe-cli/` | Root `VERSION` | PyPI: `soothe-cli` |
| soothe-daemon | `packages/soothe-daemon/` | Root `VERSION` | PyPI: `soothe-daemon` |
| soothe-sdk | `packages/soothe-sdk/` (submodule) | Own repo `pyproject.toml` | **Independent** — [mirasoth/soothe-sdk](https://github.com/mirasoth/soothe-sdk) |
| soothe-nano | `packages/soothe-nano/` (submodule) | Own repo `pyproject.toml` | **Independent** — [mirasoth/soothe-nano](https://github.com/mirasoth/soothe-nano) |

---

## Language Client Releases

Clients live in **separate git repos**, checked out as submodules under `client/`.
Each client has its **own version line** — do **not** tie them to monorepo `VERSION`.

| Client | Path | Repo | Package | Version source | Registry |
|--------|------|------|---------|----------------|----------|
| Python | `client/python` | [soothe-client-python](https://github.com/mirasoth/soothe-client-python) | `soothe-client-python` | `VERSION` | PyPI |
| TypeScript | `client/typescript` | [soothe-client-typescript](https://github.com/mirasoth/soothe-client-typescript) | `@mirasoth/soothe-client` | `package.json` | npm |
| Go | `client/go` | [soothe-client-go](https://github.com/mirasoth/soothe-client-go) | `github.com/mirasoth/soothe-client-go` | `ClientVersion` in `protocol.go` | Go modules (tag) |
| Rust | `client/rust` | [soothe-client-rust](https://github.com/mirasoth/soothe-client-rust) | `soothe-client` | `Cargo.toml` `version` | crates.io |

Docs hub: [docs/wiki/clients.md](../../../docs/wiki/clients.md).

### When to release a client

- Wire / event / RPC surface changes that apps consume
- Compatibility fixes for a new daemon / `soothe-sdk` constraint
- Feature parity across languages (prefer releasing all affected clients together)

### Client release checklist (per language)

Work **inside the submodule** (its own git remote):

1. **Bump version** in the source listed above (and any mirrored handshake constant).
2. **Update `CHANGELOG.md`** (Keep a Changelog; no IG-/RFC- in user-facing notes).
3. **Verify** locally: `make verify` (or language equivalent: `cargo test`, etc.).
4. **Commit** on `main`: `Release vX.Y.Z` (or package-appropriate message).
5. **Tag** annotated: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
6. **Push** branch + tag: `git push origin main && git push origin vX.Y.Z`.
7. **GitHub Release** (triggers `.github/workflows/release.yml`):

```bash
export GH_TOKEN="${GITHUB_PAT:-$GH_TOKEN}"
gh release create "vX.Y.Z" --title "vX.Y.Z" --notes "$(cat <<'EOF'
## Changed
- …

**Full Changelog**: https://github.com/mirasoth/soothe-client-<lang>/compare/vA.B.C...vX.Y.Z
EOF
)"
```

Publish targets by workflow:

| Client | On `release: published` |
|--------|-------------------------|
| Python | PyPI trusted publishing (`soothe-client-python`) |
| TypeScript | npm trusted publishing (`@mirasoth/soothe-client`) |
| Go | Verify only (`ClientVersion` must match tag); consumers use the git tag |
| Rust | `cargo publish` (`soothe-client`, needs `CARGO_REGISTRY_TOKEN`) |

### After client release: bump monorepo submodule

Back in the soothe monorepo:

```bash
cd client/<lang>
git fetch origin && git checkout <release-sha-or-main>
cd ../..
git add client/<lang>
git commit -m "chore(client): bump <lang> submodule to vX.Y.Z"
git push origin main
```

### Compatibility pitfalls

- **`soothe-sdk` pin**: If core bumps `soothe-sdk` major (e.g. `>=1.0.0`) but a published client still requires `soothe-sdk<1.0.0`, Docker / install resolution can fail. Release a matching client patch **before** or **with** the Docker image rebuild.
- **Event / subagent renames**: Keep wire constants aligned across all four clients (`deep_research`, …) and release each language that still ships legacy names.
- **Go**: `ClientVersion` in `protocol.go` **must** equal the release tag (CI enforces this).

### Quick version checks

```bash
cat client/python/VERSION
node -p "require('./client/typescript/package.json').version"
rg 'const ClientVersion' client/go/protocol.go
rg '^version = ' client/rust/Cargo.toml
```

---

## Troubleshooting

- **Version mismatch**: Root `VERSION` drives soothe/cli/daemon only; do not expect soothe-sdk, soothe-nano, or clients to match unless you bump them
- **soothe-sdk / soothe-nano publish fails in monorepo CI**: Expected — they are not published from this repo. Release from [mirasoth/soothe-sdk](https://github.com/mirasoth/soothe-sdk) / [mirasoth/soothe-nano](https://github.com/mirasoth/soothe-nano), then ensure the submodule pins are on PyPI before monorepo `deploy-cli` / `deploy-core` / `deploy-daemon`
- **Changelog merge conflicts**: Preserve existing entries; add new version at top
- **PyPI / npm upload fails**: Verify OIDC trusted publishing env and that the version is not already published
- **crates.io publish fails**: Check `CARGO_REGISTRY_TOKEN` and that `Cargo.toml` version is unique
- **Go release “fails” publish**: Expected — Go releases verify + tag; no artifact upload
- **Docker build fails after core release**: Check client ↔ `soothe-sdk` version constraints; release a client patch if needed
- **Missing changes**: Search git log since last tag: `git log v0.7.15..HEAD --oneline`

## Quick Reference

| Task | Command |
|------|---------|
| Check monorepo version | `cat VERSION` |
| Check soothe-sdk version | `rg '^version = ' packages/soothe-sdk/pyproject.toml` |
| Check soothe-nano version | `rg '^version = ' packages/soothe-nano/pyproject.toml` |
| Check client versions | See “Quick version checks” above |
| List recent tags | `git tag -l 'v0.8.*' \| tail -5` |
| View tag details | `git show v0.8.3` |
| Compare versions | `git log v0.8.2..v0.8.3 --oneline` |
| Build monorepo packages | `./scripts/build.sh` |
