#!/usr/bin/env bash
#
# prepare_release.sh — Package and optionally upload Tessera plugins
#
# Usage:
#   ./scripts/prepare_release.sh              # Build ZIPs only
#   ./scripts/prepare_release.sh --upload     # Build ZIPs and create GitHub release
#   ./scripts/prepare_release.sh --draft      # Build ZIPs and create draft GitHub release
#
# Version is read from plugins/tessera/metadata.txt.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
METADATA="$PROJECT_DIR/plugins/tessera/metadata.txt"
DIST_DIR="$PROJECT_DIR/dist"
PLUGINS=(tessera percentage_split stripe_hatching)

# --- Parse args ---
ACTION="none"
for arg in "$@"; do
    case "$arg" in
        --upload) ACTION="upload" ;;
        --draft)  ACTION="draft" ;;
        -h|--help)
            sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $arg" >&2
            exit 1
            ;;
    esac
done

# --- Read version ---
VERSION=$(grep -E '^version=' "$METADATA" | cut -d= -f2 | tr -d '[:space:]')
if [[ -z "$VERSION" ]]; then
    echo "ERROR: Could not read version from $METADATA" >&2
    exit 1
fi
TAG="v${VERSION}"

echo "=== Tessera Release Script ==="
echo "Version: $VERSION"
echo "Tag:     $TAG"
echo "Output:  $DIST_DIR"
echo ""

# --- Build ZIPs via package.py ---
echo "Running packaging script..."
cd "$PROJECT_DIR"
uv run python scripts/package.py --output-dir "$DIST_DIR"

# --- Create versioned ZIPs ---
echo ""
echo "Creating versioned ZIPs..."
VERSIONED_ASSETS=()
for plugin in "${PLUGINS[@]}"; do
    src="$DIST_DIR/${plugin}.zip"
    dst="$DIST_DIR/${plugin}-${VERSION}.zip"
    if [[ ! -f "$src" ]]; then
        echo "ERROR: Expected ZIP not found: $src" >&2
        exit 1
    fi
    cp "$src" "$dst"
    VERSIONED_ASSETS+=("$dst")
    echo "  $(basename "$dst")"
done

echo ""
echo "✓ Release files ready:"
ls -lh "${VERSIONED_ASSETS[@]}"

if [[ "$ACTION" == "none" ]]; then
    echo ""
    echo "ZIPs ready. To upload to GitHub:"
    echo "  ./scripts/prepare_release.sh --upload    # Create public release"
    echo "  ./scripts/prepare_release.sh --draft     # Create draft release"
    exit 0
fi

# --- Validate gh CLI ---
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI (gh) is not installed. See https://cli.github.com/" >&2
    exit 1
fi
if ! gh auth status &>/dev/null; then
    echo "ERROR: Not authenticated with GitHub CLI. Run: gh auth login" >&2
    exit 1
fi

# --- Check tag does not already exist on remote ---
if git ls-remote --tags origin | grep -q "refs/tags/${TAG}$"; then
    echo "ERROR: Tag $TAG already exists on remote. Bump version in $METADATA first." >&2
    exit 1
fi

# --- Create and push git tag ---
if ! git tag -l "$TAG" | grep -q "^${TAG}$"; then
    echo ""
    echo "Creating git tag: $TAG"
    git tag -a "$TAG" -m "Release $TAG"
fi
echo "Pushing tag to origin..."
git push origin "$TAG"

# --- Build release notes from changelog ---
# The first line of the changelog block matches the current version.
CHANGELOG_LINE=$(grep -E "^\s*${VERSION} - " "$METADATA" | head -1 | sed 's/^[[:space:]]*//')
if [[ -z "$CHANGELOG_LINE" ]]; then
    CHANGELOG_LINE="Release ${VERSION}"
fi

NOTES="## Tessera ${TAG}

${CHANGELOG_LINE}

### Assets

- \`tessera-${VERSION}.zip\` — main plugin (9 algorithms)
- \`percentage_split-${VERSION}.zip\` — standalone Percentage Split plugin
- \`stripe_hatching-${VERSION}.zip\` — standalone Stripe Hatching plugin

### Installation

1. Download the ZIP you need below
2. In QGIS: **Plugins > Manage and Install Plugins > Install from ZIP**
3. Select the downloaded ZIP and click **Install Plugin**

### Requirements

- QGIS 3.28 or later"

DRAFT_FLAG=()
if [[ "$ACTION" == "draft" ]]; then
    DRAFT_FLAG=(--draft)
    echo ""
    echo "Creating DRAFT GitHub release..."
else
    echo ""
    echo "Creating GitHub release..."
fi

# Assets with explicit display names (path#name) so the versioned filename shows on the release page.
GH_ASSETS=()
for asset in "${VERSIONED_ASSETS[@]}"; do
    GH_ASSETS+=("${asset}#$(basename "$asset")")
done

gh release create "$TAG" \
    "${GH_ASSETS[@]}" \
    --title "Tessera ${TAG}" \
    --notes "$NOTES" \
    --target main \
    "${DRAFT_FLAG[@]}"

echo ""
echo "✓ Release created successfully!"
echo "URL: $(gh release view "$TAG" --json url -q '.url')"
