# Desktop app removed from monorepo (2026-08-06)

The `apps/soothe-desktop` git submodule and macOS build script were removed from
this repository. Autopilot **job IPC** (RFC-228) remains — it is used by CLI /
`soothe-client` and is not desktop-specific.

## Removed from tree

| Item | Notes |
|------|--------|
| Submodule `apps/soothe-desktop` | Was `git@github.com:mirasoth/soothe-desktop.git` |
| `scripts/build-desktop-macos.sh` | DMG build helper |

## Archived specs / guides

| Doc | Location |
|-----|----------|
| RFC-505 Desktop Client Architecture | `docs/archive/specs/RFC-505-soothe-desktop-client.md` |
| RFC-700 Desktop App Product Redesign | `docs/archive/specs/RFC-700-desktop-app-product-redesign.md` |
| IG-465 Desktop MVP | `docs/archive/impl/IG-465-soothe-desktop-mvp.md` |
| IG-473 Desktop RFC-700 | `docs/archive/impl/IG-473-desktop-app-rfc700.md` |
| IG-607 Desktop client pin | `docs/archive/impl/IG-607-desktop-soothe-client-0.2.1.md` |
| Design drafts (2026-06-04) | `docs/archive/drafts/2026-06-04-*-desktop*.md` |

Active RFCs that formerly framed job IPC / display cards around the desktop
product (e.g. RFC-228, RFC-413) were scrubbed to CLI / protocol-1 client
language. Historical wording may remain under `docs/archive/`.

The external `mirasoth/soothe-desktop` repository is not deleted by this change.
