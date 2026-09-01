# Release & Governance

> Rules for releases, changelogs, AI attribution, and drift governance.

## No AI Co-Authors (MUST)
AI agents MUST NOT add AI tools or assistants as co-authors, reviewers, or attributions in commits, PRs, or any git metadata (Cursor, Claude, Grok, GitHub Copilot, ChatGPT, Gemini, Cody, Continue, Cline, etc.). No `Co-authored-by:`, `Generated-with:`, `Assisted-by:`, `Reviewed-by:` (for AI) trailers. No AI-tool names in `AUTHORS`, `CONTRIBUTORS`, `.mailmap`, release notes, or changelog author lines. No `--trailer` / `git commit --trailer` attributing any AI tool. `git log` reflects **human contributors only**. AI assistance may be disclosed in PR description prose, but **never** in commit metadata. If a hook or template inserts an AI co-author trailer, remove it before committing.

## Drift Governance (MUST)
Spec↔code drift is tracked through **canonical documentation mechanisms only** — not ad-hoc dashboards, cron jobs, or parallel tracking systems.
- **No drift-refresh cron infrastructure** — do not re-introduce `DriftRefreshConfig`, `DriftTriggerHook`, `builtin:drift-refresh-*` cron jobs, or drift-dashboard data dictionaries. They duplicated the design doc review process.
- **Gap-tracking scripts** (`scripts/auto_gap_report.py`, `scripts/create_drift_backlog_issues.sh`) MUST write output into `docs/impl/` with a design doc prefix and be triaged through the standard design doc lifecycle — never a separate dashboard or backlog.
- **Drift findings are design docs, not dashboards** — file `IG-XXX-gap-*.md` in `docs/impl/`. Do not create standalone drift-tracking documents outside the numbered design doc process.
- **Config fields** — do not add `cron.drift_refresh` or equivalent drift-dashboard blocks to any packaged template or `config/templates/` symlink. Drift governance is a documentation process, not a runtime config concern.
- **Wiki/docs** — deployment guides and troubleshooting indexes MUST NOT link to drift runbooks or dashboards. Document drift content under the design doc that addresses the specific gap.
- **Incidental "drift" mentions** — the word "drift" describing unrelated concepts (timestamp drift, message-shape drift, pin drift) in comments/docstrings/errors is fine. This rule governs spec↔code drift infrastructure only.

## Changelog (MUST)
Keep changelogs **brief and sharp**. Each entry is a single scannable line telling *what changed and why* — nothing more.
- One line per change — no multi-paragraph prose, no preamble, no "This PR..." narration.
- Lead with user-facing effect, not implementation detail.
- Active voice, imperative mood — "Add retry backoff to channel sends", not "Retries were added".
- Concrete and specific — name the component, config key, or command. Avoid "various improvements", "misc fixes".
- Group by release section (`Added` / `Changed` / `Fixed` / `Removed`); most impactful first.
- No internal jargon — omit design doc identifiers, ticket IDs, commit hashes from the body. Link from release notes if needed.
- No AI attribution.
- If a change isn't user-visible, it probably doesn't belong in the changelog. Internal refactors, test additions, and tooling that don't alter behavior are omitted unless they affect operators.

Good: `Add \`persistence.default_backend\` validation that rejects mixed sqlite/postgres in one process.`
Bad: `This PR updates the persistence layer to add a check for the default backend config so that users don't accidentally mix backends. (#1234, authored by...)`

## Release (MUST)
A **release** = cutting a new version across the monorepo-owned packages and publishing to PyPI + the container registry **via the GitHub release workflows** — not by manual `twine upload`, `docker push`, or local builds. The trigger is a **GitHub Release object** on a version tag, not a bare git tag.

### Pre-release gates (before tagging)
1. **Verify upstream libs** — check whether `soothe-sdk`, `soothe-client-python` (submodule), `soothe-deepagents`, and `soothe-nano` require updating. Bump submodule pins / PyPI floors when consuming new upstream versions; release those packages from their own repositories first, then pin a compatible version range here.
2. **Default to patch** — release a **patch** bump (e.g. `1.0.y → 1.0.y+1`). Do **not** cut minor/major unless explicitly approved; those require a documented breaking change and sign-off.
3. **Verify before release** — `./scripts/verify_finally.sh` MUST pass (zero lint errors, all tests green) on the commit being tagged. Pre-release CI MUST also pass before the publish job runs. Do not tag or release off a red build.
4. **PyPI-only deps must be live before releasing owned packages** — before tagging any owned package release, verify that `soothe-nano` and `soothe-deepagents` have their latest versions already published on PyPI **and** that the monorepo's pinned floors (`packages/*/pyproject.toml`) match or are below the latest PyPI version. Query `https://pypi.org/pypi/<pkg>/json` for each. If a pinned floor exceeds what is live on PyPI, the release will be uninstallable — release the upstream package from its own repo first, then proceed.

### Version bump + changelog
5. **Bump the root `VERSION` file** — `soothe`, `soothe-autopilot`, `soothe-daemon`, and `soothe-cli` all read from the root `VERSION` (via `tool.hatch.version` → `../../VERSION`). `soothe-sdk` keeps its own `packages/soothe-sdk/VERSION` on an independent 1.x line and is **not** touched by monorepo releases unless the SDK itself is being released.
6. **Promote the `[Unreleased]` block** in `CHANGELOG.md` into a dated `## [vX.Y.Z] - YYYY-MM-DD` entry with a `[Compare with previous version]` link, and reset `[Unreleased]` to empty. Follow the Keep a Changelog format.
7. **Commit the bump** — e.g. `chore(release): bump to X.Y.Z` touching only `VERSION` + `CHANGELOG.md`.

### Tag + GitHub Release (the trigger)
8. **Tag the release commit** — `git tag -a vX.Y.Z <sha> -m "vX.Y.Z"`. If the tag name was previously used by an SDK-only release, force-move it onto the new monorepo commit (`git tag -f -a vX.Y.Z <sha>`); SDK releases are preserved by their `soothe-sdk-v*` tags.
9. **Push the tag** — `git push origin vX.Y.Z --force` (force only if re-tagging).
10. **Create the GitHub Release object** — `gh release create vX.Y.Z --target main --title "vX.Y.Z" --notes-file <release-notes.md> --latest`. **This is the trigger.** A bare git tag does NOT fire the workflows — only the `release: published` event does.
11. **Do not tag from a non-main branch** unless explicitly approved.

### What the workflows do (do not replicate manually)
12. **`release.yml`** ("Release Soothe Packages") fires on `release: published`. Builds each owned package, runs tests, publishes to PyPI via trusted publishing. Each job is **idempotent** — checks `pip index versions <pkg>` and skips publishing if the version already exists. Do not pre-publish manually; if you do, the workflow will skip the upload.
13. **`release-docker.yml`** ("Release Docker Image") fires on `workflow_run` of "Release Soothe Packages" completing successfully. Waits for `soothe==X.Y.Z` and `soothe-daemon==X.Y.Z` on PyPI, resolves them together, then builds and pushes the multi-arch `soothed` image to the container registry. Does not run if the PyPI workflow failed.
14. **Do not publish to PyPI or the registry by hand.** The only exception is recovering from a transient PyPI 500/timeout on a package the workflow skipped or failed to upload — in that case, `uv build` + `uv publish dist/* --system-certs` for the affected package only, then re-trigger or let the next release confirm.

### Verify the release landed
15. **Confirm on PyPI** — `curl -sL https://pypi.org/pypi/<pkg>/json` shows `X.Y.Z` as latest for `soothe`, `soothe-autopilot`, `soothe-daemon`, `soothe-cli`. PyPI's JSON API can lag ~60s behind upload confirmations.
16. **Confirm the workflows ran green** — `gh run list --repo mirasoth/soothe --limit 5`; both "Release Soothe Packages" and "Release Docker Image" must show `success`.
17. **Confirm the GitHub Release** — `gh release view vX.Y.Z` shows `published` and `isLatest: true`.
