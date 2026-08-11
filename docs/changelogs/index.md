---
title: "Versioned Changelogs"
has_children: true
nav_order: 40
description: "Per-version API changelogs generated from git release tag diffs."
---

# Versioned Changelogs

<!-- Placeholder. Per-version entries are generated manually from release tag
     diffs and committed to docs/changelogs/. The Pages workflow rebuilds the
     site on push. -->

Each entry below documents the exported Python API surface changes between
consecutive git release tags.

Click any version for the full diff (added/removed modules and symbols).

| Version | Date | From | +Sym | -Sym |
|---|---|---|---|---|
| _No version changelogs generated yet._ | | | | |

---

## How these are generated

1. A new git tag is pushed (e.g. `v1.0.4`).
2. A maintainer runs a local diff of the exported API surface between the
   new tag and the previous release, then commits the resulting Markdown
   to `docs/changelogs/`.
3. The Pages workflow rebuilds the site on push.

See also the [human-curated CHANGELOG](../wiki/changelog.md) for release
narratives and the [API Reference](../wiki/api-reference/).
