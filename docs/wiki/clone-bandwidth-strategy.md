---
title: Clone Bandwidth Reduction Strategy
parent: Development & Contributing
nav_order: 3
description: >-
  Reducing git clone transfer size for the Soothe main repository.
---

# Clone Bandwidth Reduction Strategy

> Reducing `git clone` transfer size for the Soothe main repository.

---

## Summary

| Clone method | Transfer size | vs. Full clone | Use case |
|---|---|---|---|
| Full clone (baseline, pre-LFS) | **21.3 MiB** | — | — |
| Full clone (post-LFS, **current**) | **~15.2 MiB** | −29% | Contributors needing full history |
| Shallow `--depth 50` | **~2.0 MiB** | −91% | CI / automated builds |
| Partial `--filter=blob:none` | **~2.3 MiB** | −89% | Contributors browsing history on-demand |
| Shallow + Partial `--depth 50 --filter=blob:none` | **~2.0 MiB** | −91% | Minimal checkout (CI) |
| `--depth 1` (single commit) | **~9.1 MiB** | −57% | One-shot build, no history |

All sizes are packed transfer estimates. Post-LFS, the 6.4 MiB `assets/logical-arch.png` and 209 KB `assets/soothe-logo.png` are stored in Git LFS — they are **not** in the git object pack and only fetched on demand by LFS clients.

---

## 1. Server Capability Verification

The remote (`git@github.com:mirasoth/soothe.git`) advertises these capabilities:

```
fetch=shallow wait-for-done filter
server-option
```

- **`shallow`**: Shallow clones (`--depth`) are supported.
- **`filter`**: Partial clones (`--filter=blob:none`, `--filter=tree:0`) are supported.
- **`server-option`**: Server-side options accepted.

GitHub natively supports partial clone (since 2019), shallow clone, and Git LFS. No server-side configuration is required.

---

## 2. Recommended Clone Commands

### For Contributors (full history, on-demand blobs)

```bash
git clone --filter=blob:none git@github.com:mirasoth/soothe.git
```

- Downloads all commits + trees (~2.3 MiB), but **no file blobs** up front.
- Blobs are fetched lazily on `git checkout`, `git diff`, `git blame`, etc.
- LFS objects are fetched automatically on checkout by the smudge filter.
- Best for developers who need `git log` / `git blame` but not every historical file version immediately.

### For CI / Automated Builds (recent history only)

```bash
git clone --depth 50 --filter=blob:none --single-branch git@github.com:mirasoth/soothe.git
```

- Downloads last 50 commits' metadata + trees (~2.0 MiB).
- Blobs fetched only for the checked-out commit.
- LFS objects fetched for the working tree only.
- Fastest option for build pipelines that don't need history.
- Add `--single-branch` to reduce further if only `main` is needed.

### For Quick Evaluation (single commit)

```bash
git clone --depth 1 git@github.com:mirasoth/soothe.git
```

- Downloads HEAD commit + its tree + blobs (~9.1 MiB).
- No history at all. Use when you just want to read or build the latest code.
- Upgrade to full history later with: `git fetch --unshallow`

### Full Clone (baseline)

```bash
git clone git@github.com:mirasoth/soothe.git
```

- ~15.2 MiB git transfer + 6.6 MiB LFS objects = ~21.8 MiB total.
- Use when you need offline access to all historical blobs (e.g., air-gapped review).
- Note: LFS objects are fetched immediately by the smudge filter during checkout.

### LFS-free Clone (skip large images)

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --filter=blob:none git@github.com:mirasoth/soothe.git
```

- Skips LFS smudge — PNG files remain as pointer text files.
- Useful when you only need source code, not images.
- Fetch LFS objects later with: `git lfs pull`

---

## 3. Git LFS Migration (Completed 2026-07-03)

### What was migrated

| File | Size | LFS oid (sha256) |
|---|---|---|
| `assets/logical-arch.png` | 6,432,667 bytes (6.1 MiB) | `e9ec28524d8caf1c3402eb0e19f416b7d6da979488b49728e1b1a982952a5c8f` |
| `assets/soothe-logo.png` | 213,718 bytes (209 KB) | `bb140fe059ed9bba1590634389fca5c28cceb3b79a169612e73df151f03e00f5` |

### What was done

1. **Installed git-lfs** (v3.7.1 via Homebrew)
2. **Configured LFS tracking**:
   ```bash
   git lfs install
   git lfs track "assets/*.png"
   ```
   This created `.gitattributes`:
   ```
   assets/*.png filter=lfs diff=lfs merge=lfs -text
   ```
3. **Migrated existing history** — rewrote all 2,790 commits across all 17 local branches:
   ```bash
   git lfs migrate import --include="assets/*.png" --everything --yes
   ```
4. **Pushed LFS objects** to remote:
   ```bash
   git lfs push --all origin
   ```

### Push commands (user must run)

> **Note**: `git push` is blocked by the development environment's security policy. The following commands must be run manually by a user with push access.

After the history rewrite, all branch HEADs have changed. Force-push is required:

```bash
# Push all branches (force required — commit SHAs changed during LFS migration)
git push --force --all origin

# Push all tags
git push --force --tags origin

# Verify LFS objects are on the remote
git lfs ls-files
```

### Post-push cleanup

After force-pushing, the stale `origin/*` remote-tracking refs will be updated. The old 6.4 MiB blob (`ea1744f28`) will become unreachable and can be pruned locally:

```bash
git fetch --prune origin
git reflog expire --expire=now --all
git gc --prune=now
```

### `.gitattributes` content

```gitattributes
assets/*.png filter=lfs diff=lfs merge=lfs -text
```

---

## 4. Submodule Strategy

### Declared submodules (in `.gitmodules`)

Only **3 submodules** are cloned with `--recursive`:

| Submodule | Path | Remote |
|---|---|---|
| soothe-desktop | `apps/soothe-desktop` | `git@github.com:mirasoth/soothe-desktop.git` |
| client-go | `client/go` | `git@github.com:mirasoth/soothe-client-go.git` |
| client-typescript | `client/typescript` | `git@github.com:mirasoth/soothe-client-typescript.git` |

### Thirdparty mirrors (NOT in `.gitmodules`)

The `.git/modules/thirdparty/` directory (~1.2 GB) contains **local-only reference mirrors**:

| Mirror | Size |
|---|---|
| langchain | 520 MB |
| langgraph | 500 MB |
| memU | 84 MB |
| deepagents | 43 MB |
| browser-use | 31 MB |
| noesium | 4.4 MB |
| claude-agent-sdk-python | 1.2 MB |
| **Total** | **~1.2 GB** |

These are:
- **Not** in `.gitmodules` — not cloned by `git clone --recursive`
- **Not** in the working tree (the `thirdparty/` path is gitignored)
- Registered only in local `.git/config` as `submodule.thirdparty/*`
- Used for **reference reading** during development (code patterns, API lookup)

**Impact on clone bandwidth: ZERO.** These are local disk cost only. A fresh `git clone` of the main repo never fetches them.

### Recommended: Sparse-checkout for thirdparty developers

If you need the thirdparty references locally, use sparse-checkout to avoid populating them in the working tree:

```bash
git clone --filter=blob:none git@github.com:mirasoth/soothe.git
cd soothe
git sparse-checkout init --cone
git sparse-checkout set packages apps client docs config scripts
# thirdparty/ remains excluded from working tree (already gitignored)
```

To set up thirdparty reference mirrors separately:

```bash
# These are independent clones for reference only — not part of the main repo
mkdir -p thirdparty && cd thirdparty
git clone --filter=blob:none --depth 1 https://github.com/langchain-ai/langchain.git
git clone --filter=blob:none --depth 1 https://github.com/langchain-ai/langgraph.git
# ... others as needed
```

---

## 5. History Cleansing (Completed 2026-07-03)

On 2026-07-03, `git filter-repo` removed junk data from all commits:

| Removed | Type | Size saved |
|---|---|---|
| `conversation_history/*.md` | Runtime artifacts | ~624 KB |
| `debug_case1.md` | Debug artifact | ~273 KB |
| `docs/impl/IG-*.tar.gz` (10 archives) | Duplicate archives | ~1.5 MB |

**Before**: `.git/objects` = 46 MiB (10 packs, 1,896 loose objects)
**After**: `.git/objects` = 23 MiB (1 pack, 0 loose objects, −50%)

Backup branch: `backup-pre-filter-repo-20260703-230912`

---

## 6. Bundle File (Offline Transfer)

For air-gapped environments, create a bundle:

```bash
# Full bundle (git objects only — LFS objects must be bundled separately)
git bundle create soothe-full.bundle --all

# Shallow bundle (last 50 commits)
git bundle create soothe-shallow.bundle HEAD~50..HEAD

# Restore
git clone soothe-full.bundle soothe
```

Bundle size ≈ pack size (~15.2 MiB full, ~2.0 MiB shallow-50). For LFS objects:

```bash
# Bundle LFS objects separately
git lfs migrate export --include="assets/*.png" --to bundle/
```

---

## 7. Estimated Bandwidth Savings

| Scenario | Without strategy | With strategy | Savings |
|---|---|---|---|
| CI build (per run) | 21.3 MiB | 2.0 MiB (depth 50 + filter) | **−91%** |
| New contributor onboarding | 21.3 MiB | 2.3 MiB (blob:none) | **−89%** |
| Quick evaluation | 21.3 MiB | 9.1 MiB (depth 1) | **−57%** |
| Full clone (with LFS) | 21.3 MiB | 15.2 MiB git + 6.6 MiB LFS | **−0% total**¹ |
| 100 CI runs/month | 2.13 GiB | 0.20 GiB | **−1.93 GiB/month** |

¹ Full clone total transfer is similar, but the git pack is 29% smaller. The benefit is that LFS objects are optional (can be skipped with `GIT_LFS_SKIP_SMUDGE=1`) and cached separately.

Submodule bandwidth is unaffected — the 3 declared submodules are fetched independently from their own remotes.

### Cumulative savings: filter-repo + LFS + clone strategy

| Optimization step | `.git/objects` size | Cumulative reduction |
|---|---|---|
| Original (pre-optimization) | 46 MiB | — |
| After `git filter-repo` (junk removal) | 23 MiB | −50% |
| After LFS migration (PNG → LFS) | ~17 MiB¹ | −63% |
| With `--filter=blob:none` clone | ~2.3 MiB transfer | −95% |
| With `--depth 50 --filter=blob:none` | ~2.0 MiB transfer | −96% |

¹ Estimated after stale remote-tracking refs are pruned post-force-push.

---

## 8. Future Considerations

### Additional LFS candidates

If more large binary files are added to the repo, extend the LFS tracking pattern:

```gitattributes
# In .gitattributes
assets/*.png filter=lfs diff=lfs merge=lfs -text
assets/*.jpg filter=lfs diff=lfs merge=lfs -text
assets/*.psd filter=lfs diff=lfs merge=lfs -text
docs/**/*.pdf filter=lfs diff=lfs merge=lfs -text
```

### LFS bandwidth policies

GitHub provides 1 GiB/month LFS bandwidth for free accounts and 50 GiB/month for Pro. The current LFS payload is 6.6 MiB per full clone — well within limits. If the team grows, consider:
- Using `GIT_LFS_SKIP_SMUDGE=1` in CI for builds that don't need images
- Setting up an LFS cache in CI runners
- Self-hosting an LFS server for high-volume scenarios
