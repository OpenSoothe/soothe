# IG-621: soothe-sdk 1.0.0 legacy API removal

**Guide**: IG-621  
**Title**: Remove SDK compat shims and root re-exports; ship stable 1.0.0  
**Created**: 2026-07-17  
**Related**: IG-612 (Phase B migration window), RFC-610 (SDK module structure)  
**Status**: In progress

---

## Goal

Close the IG-612 Phase B migration window and ship **soothe-sdk 1.0.0** with a clean public import surface:

- No `soothe_sdk.client.*` or `soothe_sdk.langchain_wire` shims
- Root package exports version metadata only
- Plugin types use full names (`PluginManifest`, `PluginContext`, `PluginHealth`)
- All in-repo consumers use package-level imports only

## Removed surfaces

| Removed | Canonical replacement |
|---------|----------------------|
| `soothe_sdk.client` / `.config` / `.wire` / `.protocol` | `soothe_sdk.paths` / `soothe_sdk.wire` / `.wire.codec` / `.wire.protocol` |
| `soothe_sdk.langchain_wire` | `soothe_sdk.wire.codec` |
| Root re-exports (`plugin`, `SOOTHE_HOME`, protocols, …) | Subpackage imports |
| `Manifest` / `Context` / `Health` / `Depends` aliases | `PluginManifest` / `PluginContext` / `PluginHealth` / `library` |

## Exit criteria

- [x] Shim modules deleted
- [x] Root `__init__` is version-only
- [x] Plugin package exports full type names only
- [x] All in-repo consumers migrated
- [x] Pins raised to `soothe-sdk>=1.0.0,<2.0.0`
- [x] `./scripts/verify_finally.sh` green
- [x] soothe-sdk `1.0.0` released

**Status**: Complete (2026-07-17) — PyPI `soothe-sdk==1.0.0`, GitHub release `soothe-sdk-v1.0.0`
