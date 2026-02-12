# Release Process

This document describes how to create and publish Tessera releases using GitHub's native release system.

## Overview

Tessera releases are published on GitHub at: https://github.com/rafdouglas/tessera/releases

Each release includes three plugin ZIP files:
- `tessera-X.Y.Z.zip` - Main plugin with all 9 algorithms
- `percentage_split-X.Y.Z.zip` - Standalone Percentage Split plugin
- `stripe_hatching-X.Y.Z.zip` - Standalone Stripe Hatching plugin

## Two Release Methods

### Method 1: Automated (Recommended)

When you push a version tag, GitHub Actions automatically creates the release.

**Steps:**

1. **Update version number** in `plugins/tessera/metadata.txt`:
   ```
   version=0.5.5
   ```

2. **Commit changes:**
   ```bash
   git add plugins/tessera/metadata.txt
   git commit -m "Bump version to 0.5.5"
   ```

3. **Create and push a tag:**
   ```bash
   git tag -a v0.5.5 -m "Release 0.5.5"
   git push origin main
   git push origin v0.5.5
   ```

4. **GitHub Actions takes over:**
   - Workflow runs automatically (`.github/workflows/release.yml`)
   - Packages all three plugins
   - Creates GitHub release with version tag
   - Attaches ZIP files as release assets
   - Generates release notes

5. **Verify the release** at https://github.com/rafdouglas/tessera/releases

### Method 2: Manual

Create the release manually through the GitHub web interface.

**Steps:**

1. **Prepare release files locally:**
   ```bash
   # Update version in plugins/tessera/metadata.txt first
   ./scripts/prepare_release.sh
   ```

   This creates versioned ZIPs in `releases/`:
   - `releases/tessera-X.Y.Z.zip`
   - `releases/percentage_split-X.Y.Z.zip`
   - `releases/stripe_hatching-X.Y.Z.zip`

2. **Create and push a tag:**
   ```bash
   git tag -a v0.5.5 -m "Release 0.5.5"
   git push origin main
   git push origin v0.5.5
   ```

3. **Create release on GitHub:**
   - Go to https://github.com/rafdouglas/tessera/releases
   - Click **"Draft a new release"**
   - Choose tag: Select `v0.5.5` from dropdown
   - Release title: `Tessera 0.5.5`
   - Click **"Generate release notes"** for automatic changelog
   - Edit description as needed
   - Drag and drop the three ZIP files from `releases/` folder
   - Mark as pre-release if needed (uncheck for stable releases)
   - Click **"Publish release"**

## Release Checklist

Before creating a release, ensure:

- [ ] All tests pass: `flatpak run --command=python3 org.qgis.qgis -m pytest tests/ -v`
- [ ] Version updated in `plugins/tessera/metadata.txt`
- [ ] Changelog updated in `plugins/tessera/metadata.txt`
- [ ] README.md reflects current version and features
- [ ] All changes committed and pushed to main branch
- [ ] No uncommitted changes in working directory

## Release Notes Template

When creating manual release notes, use this format:

```markdown
## Tessera X.Y.Z

Cartographic ideogram toolkit for QGIS with 9 algorithms.

### What's New

- Feature 1 description
- Feature 2 description
- Bug fix 1 description

### Installation

Download the appropriate ZIP file:
- **tessera-X.Y.Z.zip** - Main plugin with all 9 algorithms
- **percentage_split-X.Y.Z.zip** - Standalone Percentage Split plugin
- **stripe_hatching-X.Y.Z.zip** - Standalone Stripe Hatching plugin

**Install via QGIS Plugin Manager** (recommended) or manually:
1. Extract ZIP to `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
2. Restart QGIS
3. Enable in **Plugins → Manage and Install Plugins**

See the [README](https://github.com/rafdouglas/tessera) for full documentation.

### Requirements

- QGIS 3.28 or later
- No external dependencies
```

## Troubleshooting

**GitHub Actions workflow fails:**
- Check workflow run logs at https://github.com/rafdouglas/tessera/actions
- Verify `scripts/package.py` runs without errors locally
- Ensure tag format matches `v*` pattern (e.g., `v0.5.5`)

**Manual release upload fails:**
- Ensure ZIP files are under 2 GiB each (current sizes ~15-75 KB)
- Check you have write permissions to the repository
- Verify tag exists: `git tag -l`

**Version mismatch:**
- Version in `metadata.txt` should match tag without 'v' prefix
- Tag: `v0.5.5` → metadata.txt: `version=0.5.5`
