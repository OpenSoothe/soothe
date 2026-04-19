# Version Management

## Single Version Source

All packages in the monorepo (soothe, soothe-cli, soothe-sdk) share a single version defined in the root `VERSION` file.

## How to Update Version

To update the version for all packages:

```bash
# Edit the VERSION file
echo "0.4.0" > VERSION

# Or use any text editor
vim VERSION
```

That's it! All packages will automatically use the new version.

## How It Works

Each package's `pyproject.toml`:

1. Uses `dynamic = ["version"]` to indicate version is dynamic
2. Configures `[tool.hatch.version]` with `path = "../../VERSION"`
3. Hatch reads the VERSION file during build

## Verification

You can verify the version for each package:

```bash
cd packages/soothe-sdk && hatch version
cd packages/soothe-cli && hatch version
cd packages/soothe && hatch version
```

All should output the same version from `VERSION`.

## Current Version

```
0.3.4
```